from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


SCHEMA = """
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
    search_tsv   TSVECTOR,
    UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS pages_fetched_at_idx ON pages (fetched_at DESC);

-- Add the search column on pre-existing tables that lack it.
ALTER TABLE pages ADD COLUMN IF NOT EXISTS search_tsv TSVECTOR;

-- Full-text search index over title + text (weighted), maintained by trigger.
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
"""


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute(SCHEMA)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        async with acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    pool = await init_pool()
    async with pool.acquire() as conn:
        yield conn


def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d.pop("search_tsv", None)
    for k in ("links", "metadata"):
        v = d.get(k)
        if isinstance(v, str):
            d[k] = json.loads(v)
    if isinstance(d.get("fetched_at"), datetime):
        d["fetched_at"] = d["fetched_at"].isoformat()
    return d


async def upsert_page(page: dict[str, Any]) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pages (url, final_url, status, title, text, html, links, metadata, render_mode, error)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10)
            ON CONFLICT (url) DO UPDATE SET
                final_url   = EXCLUDED.final_url,
                status      = EXCLUDED.status,
                title       = EXCLUDED.title,
                text        = EXCLUDED.text,
                html        = EXCLUDED.html,
                links       = EXCLUDED.links,
                metadata    = EXCLUDED.metadata,
                render_mode = EXCLUDED.render_mode,
                error       = EXCLUDED.error,
                fetched_at  = NOW()
            RETURNING id, url, final_url, status, title, text, links, metadata, render_mode, error, fetched_at
            """,
            page["url"],
            page.get("final_url"),
            page.get("status"),
            page.get("title"),
            page.get("text"),
            page.get("html"),
            json.dumps(page.get("links", [])),
            json.dumps(page.get("metadata", {})),
            page["render_mode"],
            page.get("error"),
        )
    return _row_to_dict(row)  # type: ignore[return-value]


async def get_page_by_url(url: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)
    return _row_to_dict(row)


async def get_page_by_id(page_id: int) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pages WHERE id = $1", page_id)
    return _row_to_dict(row)


async def delete_page(page_id: int) -> bool:
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM pages WHERE id = $1", page_id)
    return result.rsplit(" ", 1)[-1] != "0"


async def count_pages() -> int:
    async with acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM pages") or 0


async def list_pages(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, url, final_url, status, title, render_mode, fetched_at "
            "FROM pages ORDER BY fetched_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


async def search_pages(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Full-text search ranked by relevance, with an ILIKE fallback for URLs/short terms."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, url, final_url, status, title, render_mode, fetched_at,
                   substring(text from 1 for 400) AS text,
                   ts_rank(search_tsv, websearch_to_tsquery('english', $1)) AS rank
            FROM pages
            WHERE search_tsv @@ websearch_to_tsquery('english', $1)
               OR url ILIKE $2
            ORDER BY rank DESC NULLS LAST, fetched_at DESC
            LIMIT $3
            """,
            query,
            f"%{query}%",
            limit,
        )
    out = []
    for r in rows:
        d = _row_to_dict(r)
        if d is not None:
            d.pop("rank", None)
            out.append(d)
    return out
