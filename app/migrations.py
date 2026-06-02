"""Lightweight, dependency-free SQL migrations.

Each migration is an ordered (version, name, sql) tuple applied exactly once and
recorded in `schema_migrations`. This gives us real, versioned, append-only
schema evolution without pulling in Alembic. Statements within a migration run
inside a transaction so a partial apply never leaves a half-migrated schema.
"""
from __future__ import annotations

import asyncpg

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial pages table",
        """
        CREATE TABLE IF NOT EXISTS pages (
            id           BIGSERIAL PRIMARY KEY,
            url          TEXT NOT NULL,
            final_url    TEXT,
            status       INTEGER,
            title        TEXT,
            text         TEXT,
            html         TEXT,
            links        JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
            render_mode  TEXT NOT NULL,
            error        TEXT,
            fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (url)
        );
        CREATE INDEX IF NOT EXISTS pages_fetched_at_idx ON pages (fetched_at DESC);
        """,
    ),
    (
        2,
        "full-text search vector + trigger",
        """
        ALTER TABLE pages ADD COLUMN IF NOT EXISTS search_tsv TSVECTOR;
        CREATE INDEX IF NOT EXISTS pages_search_tsv_idx ON pages USING GIN (search_tsv);
        CREATE OR REPLACE FUNCTION pages_search_tsv_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_tsv :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.text, '')), 'B');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS pages_search_tsv_trigger ON pages;
        CREATE TRIGGER pages_search_tsv_trigger
            BEFORE INSERT OR UPDATE OF title, text ON pages
            FOR EACH ROW EXECUTE FUNCTION pages_search_tsv_update();
        """,
    ),
    (
        3,
        "extraction + conditional-recrawl columns; compressed html",
        """
        ALTER TABLE pages ADD COLUMN IF NOT EXISTS markdown TEXT;
        ALTER TABLE pages ADD COLUMN IF NOT EXISTS etag TEXT;
        ALTER TABLE pages ADD COLUMN IF NOT EXISTS last_modified TEXT;
        ALTER TABLE pages ADD COLUMN IF NOT EXISTS content_hash TEXT;
        ALTER TABLE pages ADD COLUMN IF NOT EXISTS html_gz BYTEA;
        ALTER TABLE pages DROP COLUMN IF EXISTS html;
        """,
    ),
    (
        4,
        "durable crawl jobs",
        """
        CREATE TABLE IF NOT EXISTS crawl_jobs (
            id           TEXT PRIMARY KEY,
            status       TEXT NOT NULL,
            progress     INTEGER NOT NULL DEFAULT 0,
            total        INTEGER,
            request      JSONB NOT NULL DEFAULT '{}'::jsonb,
            pages        JSONB NOT NULL DEFAULT '[]'::jsonb,
            error        TEXT,
            webhook_url  TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS crawl_jobs_created_at_idx ON crawl_jobs (created_at DESC);
        """,
    ),
    (
        5,
        "partial indexes for /stats aggregates",
        """
        CREATE INDEX IF NOT EXISTS pages_errors_idx ON pages (id) WHERE error IS NOT NULL;
        CREATE INDEX IF NOT EXISTS pages_blocked_idx ON pages (id) WHERE metadata ? 'block';
        """,
    ),
    (
        6,
        "trigram index for URL ILIKE search fallback",
        # The search endpoint's `url ILIKE '%q%'` fallback can't use a btree
        # index (leading wildcard) and degrades to a seq scan on large tables. A
        # pg_trgm GIN index fixes that. Wrapped in a DO block whose exception
        # handler skips it if the extension can't be created (no privilege / not
        # bundled on managed Postgres), so the migration still succeeds — the
        # query stays correct, just unindexed, exactly as before.
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE INDEX IF NOT EXISTS pages_url_trgm_idx ON pages USING gin (url gin_trgm_ops);
        EXCEPTION WHEN OTHERS THEN
            -- Best-effort: if the extension can't be created (no privilege / not
            -- bundled), skip the index rather than failing startup. Search stays
            -- correct, just unindexed for the ILIKE fallback.
            RAISE NOTICE 'pg_trgm unavailable; skipping URL trigram index (%)', SQLERRM;
        END
        $$;
        """,
    ),
]


async def apply_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    applied = {
        r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")
    }
    for version, name, sql in MIGRATIONS:
        if version in applied:
            continue
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                version,
                name,
            )
