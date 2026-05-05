from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

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
    UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS pages_fetched_at_idx ON pages (fetched_at DESC);
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


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    pool = await init_pool()
    async with pool.acquire() as conn:
        yield conn


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
            RETURNING *
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
    pattern = f"%{query}%"
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, url, final_url, status, title, render_mode, fetched_at,
                   substring(text from 1 for 400) AS text
            FROM pages
            WHERE title ILIKE $1 OR text ILIKE $1 OR url ILIKE $1
            ORDER BY fetched_at DESC
            LIMIT $2
            """,
            pattern,
            limit,
        )
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]
