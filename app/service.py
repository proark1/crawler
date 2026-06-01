"""Shared crawl orchestration used by both the REST API and the MCP server.

Keeping this in one place means both entry points apply the same SSRF guards,
robots handling, conditional re-crawl/caching, persistence, and HTML stripping —
so the MCP tools never drift behind the HTTP API.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from . import crawler, db, observability
from .config import settings


def make_cache_lookup(store: bool) -> Callable | None:
    """A best-effort `url -> stored row` lookup, or None when not storing."""
    if not store:
        return None

    async def lookup(url: str) -> dict | None:
        try:
            return await db.get_page_by_url(url)
        except Exception:  # noqa: BLE001 -- caching is best-effort
            return None

    return lookup


async def run_crawl(
    *,
    url: str,
    render: Literal["auto", "static", "js"] = "auto",
    follow_links: bool = False,
    max_depth: int = 1,
    max_pages: int = 10,
    same_host_only: bool = True,
    store: bool = True,
    use_sitemap: bool = True,
    on_progress: Callable[[Any], None] | None = None,
) -> list[dict]:
    """Crawl one URL or a site, persist results, and return HTML-stripped pages.

    Honours conditional re-crawl: fresh stored copies (within RECRAWL_MAX_AGE)
    are served without refetching, and `304 Not Modified` reuses stored content.
    """
    if follow_links:
        results = await crawler.crawl_site(
            url,
            render=render,
            max_depth=max_depth,
            max_pages=max_pages,
            same_host_only=same_host_only,
            cache_lookup=make_cache_lookup(store),
            on_page_crawled=on_progress,
            use_sitemap=use_sitemap,
        )
    else:
        cached = None
        if store:
            lookup = make_cache_lookup(True)
            row = await lookup(url) if lookup else None
            if row and crawler.is_fresh(row, settings.recrawl_max_age):
                return [{**row, "from_cache": True}]
            if row:
                cached = {"etag": row.get("etag"), "last_modified": row.get("last_modified")}
        if cached:
            res = await crawler.crawl_one(url, render=render, cached=cached)
        else:
            res = await crawler.crawl_one(url, render=render)
        if res.get("not_modified") and store:
            row = await db.get_page_by_url(url)
            results = [row or res]
        else:
            results = [res]

    observability.record_pages(results)

    # Persist freshly crawled pages (skip rows that came straight from cache).
    to_store = [r for r in results if not r.get("from_cache")]
    if store and to_store:
        stored = await asyncio.gather(*(db.upsert_page(r) for r in to_store))
        stored_by_url = {s["url"]: s for s in stored}
        results = [stored_by_url.get(r["url"], r) for r in results]
    for r in results:
        r.pop("html", None)
    return [dict(r) for r in results]
