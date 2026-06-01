from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None
_pool_lock: Any = None  # set lazily to avoid importing asyncio at module load


SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id           BIGSERIAL PRIMARY KEY,
    url          TEXT NOT NULL,
    final_url    TEXT,
    status       INTEGER,
    title        TEXT,
    text         TEXT,
    markdown     TEXT,
    html         TEXT,
    links        JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    render_mode  TEXT NOT NULL,
    error        TEXT,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (url)
);

ALTER TABLE pages ADD COLUMN IF NOT EXISTS markdown TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(title, '') || ' ' || coalesce(text, '') || ' ' || coalesce(url, ''))
    ) STORED;

CREATE INDEX IF NOT EXISTS pages_fetched_at_idx ON pages (fetched_at DESC);
CREATE INDEX IF NOT EXISTS pages_search_idx ON pages USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS crawl_jobs (
    id           BIGSERIAL PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'pending',
    params       JSONB NOT NULL DEFAULT '{}'::jsonb,
    total        INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_pages (
    job_id   BIGINT NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
    page_id  BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (job_id, page_id)
);
CREATE INDEX IF NOT EXISTS job_pages_job_idx ON job_pages (job_id, position);
"""

_PAGE_LIST_COLS = "id, url, final_url, status, title, render_mode, error, fetched_at"


async def init_pool() -> asyncpg.Pool:
    global _pool, _pool_lock
    if _pool is not None:
        return _pool
    if _pool_lock is None:
        import asyncio

        _pool_lock = asyncio.Lock()
    async with _pool_lock:
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
    """Lightweight connectivity check for the health endpoint."""
    try:
        async with acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    pool = await init_pool()
    async with pool.acquire() as conn:
        yield conn


def _clean(value: Any) -> Any:
    """Strip NUL bytes that Postgres TEXT columns reject."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("links", "metadata"):
        v = d.get(k)
        if isinstance(v, str):
            d[k] = json.loads(v)
    if isinstance(d.get("fetched_at"), datetime):
        d["fetched_at"] = d["fetched_at"].isoformat()
    return d


_UPSERT_SQL = """
    INSERT INTO pages
        (url, final_url, status, title, text, markdown, html, links, metadata, render_mode, error)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11)
    ON CONFLICT (url) DO UPDATE SET
        final_url   = EXCLUDED.final_url,
        status      = EXCLUDED.status,
        title       = EXCLUDED.title,
        text        = EXCLUDED.text,
        markdown    = EXCLUDED.markdown,
        html        = EXCLUDED.html,
        links       = EXCLUDED.links,
        metadata    = EXCLUDED.metadata,
        render_mode = EXCLUDED.render_mode,
        error       = EXCLUDED.error,
        fetched_at  = NOW()
    RETURNING *
"""


def _upsert_args(page: dict[str, Any]) -> tuple:
    return (
        _clean(page["url"]),
        _clean(page.get("final_url")),
        page.get("status"),
        _clean(page.get("title")),
        _clean(page.get("text")),
        _clean(page.get("markdown")),
        _clean(page.get("html")),
        json.dumps(page.get("links", [])),
        json.dumps(page.get("metadata", {})),
        page["render_mode"],
        _clean(page.get("error")),
    )


async def upsert_page(page: dict[str, Any]) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(_UPSERT_SQL, *_upsert_args(page))
    return _row_to_dict(row)  # type: ignore[return-value]


async def get_page_by_url(url: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pages WHERE url = $1", url)
    return _row_to_dict(row)


async def get_page_by_id(page_id: int) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pages WHERE id = $1", page_id)
    return _row_to_dict(row)


async def list_pages(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_PAGE_LIST_COLS} FROM pages ORDER BY fetched_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


async def count_pages() -> int:
    async with acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM pages")  # type: ignore[return-value]


async def search_pages(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Full-text search with ranking, falling back to URL substring match."""
    async with acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_PAGE_LIST_COLS},
                   substring(text from 1 for 400) AS text,
                   ts_rank(search_vector, websearch_to_tsquery('english', $1)) AS rank
            FROM pages
            WHERE search_vector @@ websearch_to_tsquery('english', $1)
               OR url ILIKE $2
            ORDER BY rank DESC, fetched_at DESC
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


# --- Jobs -----------------------------------------------------------------

async def create_job(params: dict[str, Any]) -> int:
    async with acquire() as conn:
        return await conn.fetchval(  # type: ignore[return-value]
            "INSERT INTO crawl_jobs (status, params) VALUES ('running', $1::jsonb) RETURNING id",
            json.dumps(params),
        )


async def update_job(
    job_id: int, *, status: str | None = None, total: int | None = None, error: str | None = None
) -> None:
    sets = ["updated_at = NOW()"]
    args: list[Any] = []
    if status is not None:
        args.append(status)
        sets.append(f"status = ${len(args)}")
    if total is not None:
        args.append(total)
        sets.append(f"total = ${len(args)}")
    if error is not None:
        args.append(error)
        sets.append(f"error = ${len(args)}")
    args.append(job_id)
    async with acquire() as conn:
        await conn.execute(
            f"UPDATE crawl_jobs SET {', '.join(sets)} WHERE id = ${len(args)}", *args
        )


async def add_job_page(job_id: int, page: dict[str, Any]) -> dict[str, Any]:
    """Upsert a page and link it to a job in one transaction."""
    async with acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(_UPSERT_SQL, *_upsert_args(page))
            page_id = row["id"]
            position = await conn.fetchval(
                "SELECT count(*) FROM job_pages WHERE job_id = $1", job_id
            )
            await conn.execute(
                "INSERT INTO job_pages (job_id, page_id, position) VALUES ($1, $2, $3) "
                "ON CONFLICT (job_id, page_id) DO NOTHING",
                job_id,
                page_id,
                position,
            )
    return _row_to_dict(row)  # type: ignore[return-value]


async def get_job(job_id: int) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM crawl_jobs WHERE id = $1", job_id)
    if row is None:
        return None
    d = dict(row)
    if isinstance(d.get("params"), str):
        d["params"] = json.loads(d["params"])
    for k in ("created_at", "updated_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


async def get_job_pages(job_id: int) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            f"SELECT p.{', p.'.join(_PAGE_LIST_COLS.split(', '))} "
            "FROM job_pages jp JOIN pages p ON p.id = jp.page_id "
            "WHERE jp.job_id = $1 ORDER BY jp.position",
            job_id,
        )
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]
