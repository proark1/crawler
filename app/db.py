from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import asyncpg

from .config import settings
from .migrations import apply_migrations

_pool: asyncpg.Pool | None = None

# Columns returned to callers (everything except the compressed HTML blob and tsvector).
_PAGE_COLS = (
    "id, url, final_url, status, title, text, markdown, links, metadata, "
    "render_mode, error, etag, last_modified, content_hash, fetched_at"
)


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
        async with _pool.acquire() as conn:
            await apply_migrations(conn)
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


def _gz(html: str | None) -> bytes | None:
    if not html or not settings.store_html:
        return None
    return gzip.compress(html.encode("utf-8", "replace"))


def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d.pop("search_tsv", None)
    html_gz = d.pop("html_gz", None)
    if html_gz is not None:
        d["html"] = gzip.decompress(html_gz).decode("utf-8", "replace")
    for k in ("links", "metadata", "pages", "request"):
        v = d.get(k)
        if isinstance(v, str):
            d[k] = json.loads(v)
    for k in ("fetched_at", "created_at", "updated_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


# --------------------------------------------------------------------------- #
# Pages                                                                       #
# --------------------------------------------------------------------------- #


async def upsert_page(page: dict[str, Any]) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO pages (url, final_url, status, title, text, markdown, html_gz,
                               links, metadata, render_mode, error, etag, last_modified,
                               content_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13, $14)
            ON CONFLICT (url) DO UPDATE SET
                final_url     = EXCLUDED.final_url,
                status        = EXCLUDED.status,
                title         = EXCLUDED.title,
                text          = EXCLUDED.text,
                markdown      = EXCLUDED.markdown,
                html_gz       = EXCLUDED.html_gz,
                links         = EXCLUDED.links,
                metadata      = EXCLUDED.metadata,
                render_mode   = EXCLUDED.render_mode,
                error         = EXCLUDED.error,
                etag          = EXCLUDED.etag,
                last_modified = EXCLUDED.last_modified,
                content_hash  = EXCLUDED.content_hash,
                fetched_at    = NOW()
            RETURNING {_PAGE_COLS}
            """,
            page["url"],
            page.get("final_url"),
            page.get("status"),
            page.get("title"),
            page.get("text"),
            page.get("markdown"),
            _gz(page.get("html")),
            json.dumps(page.get("links", [])),
            json.dumps(page.get("metadata", {})),
            page["render_mode"],
            page.get("error"),
            page.get("etag"),
            page.get("last_modified"),
            page.get("content_hash"),
        )
    return _row_to_dict(row)  # type: ignore[return-value]


async def get_page_by_url(url: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_PAGE_COLS} FROM pages WHERE url = $1", url
        )
    return _row_to_dict(row)


async def get_page_by_id(page_id: int) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_PAGE_COLS} FROM pages WHERE id = $1", page_id
        )
    return _row_to_dict(row)


async def get_page_html(page_id: int) -> str | None:
    async with acquire() as conn:
        blob = await conn.fetchval("SELECT html_gz FROM pages WHERE id = $1", page_id)
    if blob is None:
        return None
    return gzip.decompress(blob).decode("utf-8", "replace")


async def delete_page(page_id: int) -> bool:
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM pages WHERE id = $1", page_id)
    return result.rsplit(" ", 1)[-1] != "0"


async def count_pages() -> int:
    async with acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM pages") or 0


async def stats() -> dict[str, int]:
    """Aggregate counts for the dashboard: total, errored, and bot-blocked pages."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT count(*) AS total, "
            "count(*) FILTER (WHERE error IS NOT NULL) AS errors, "
            "count(*) FILTER (WHERE metadata ? 'block') AS blocked "
            "FROM pages"
        )
    return {
        "total": row["total"] or 0,
        "errors": row["errors"] or 0,
        "blocked": row["blocked"] or 0,
    }


async def list_pages(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, url, final_url, status, title, render_mode, fetched_at "
            "FROM pages ORDER BY fetched_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


async def iter_all_pages() -> AsyncIterator[dict[str, Any]]:
    """Stream every page (lightweight columns) for export via a server-side cursor.

    A cursor avoids the O(N^2) cost of deep LIMIT/OFFSET pagination and keeps
    memory flat regardless of table size.
    """
    async with acquire() as conn, conn.transaction():
        async for row in conn.cursor(
            "SELECT id, url, final_url, status, title, render_mode, fetched_at "
            "FROM pages ORDER BY fetched_at DESC"
        ):
            d = _row_to_dict(row)
            if d is not None:
                yield d


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


# --------------------------------------------------------------------------- #
# Jobs (durable mirror of the in-memory registry)                             #
# --------------------------------------------------------------------------- #


async def upsert_job(job: dict[str, Any]) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO crawl_jobs (id, status, progress, total, request, pages, error, webhook_url, updated_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, NOW())
            ON CONFLICT (id) DO UPDATE SET
                status      = EXCLUDED.status,
                progress    = EXCLUDED.progress,
                total       = EXCLUDED.total,
                pages       = EXCLUDED.pages,
                error       = EXCLUDED.error,
                updated_at  = NOW()
            """,
            job["id"],
            job["status"],
            job.get("progress", 0),
            job.get("total"),
            json.dumps(job.get("request", {})),
            json.dumps(job.get("pages", [])),
            job.get("error"),
            job.get("webhook_url"),
        )


async def reap_orphaned_jobs() -> int:
    """Fail jobs left 'running'/'pending' by a previous process (in-process jobs
    don't survive a restart). Returns the number reaped."""
    async with acquire() as conn:
        result = await conn.execute(
            "UPDATE crawl_jobs SET status = 'error', "
            "error = 'orphaned: process restarted', updated_at = NOW() "
            "WHERE status IN ('running', 'pending')"
        )
    return int(result.rsplit(" ", 1)[-1] or 0)


async def get_job_row(job_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, progress, total, pages, error, created_at, updated_at "
            "FROM crawl_jobs WHERE id = $1",
            job_id,
        )
    return _row_to_dict(row)


async def list_jobs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, status, progress, total, error, created_at, updated_at "
            "FROM crawl_jobs ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]
