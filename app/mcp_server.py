"""MCP server exposing the crawler over stdio.

Run locally:
    python -m app.mcp_server
"""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from mcp.server.fastmcp import FastMCP

from . import db
from .crawler import crawl_one, crawl_site

mcp = FastMCP("crawler")


def _strip_html(page: dict) -> dict:
    page = dict(page)
    page.pop("html", None)
    return page


async def _store(results: list[dict]) -> list[dict]:
    saved = await asyncio.gather(
        *(db.upsert_page(r) for r in results), return_exceptions=True
    )
    out = []
    for original, result in zip(results, saved, strict=True):
        out.append(original if isinstance(result, Exception) else result)
    return out


@mcp.tool()
async def crawl(
    url: str,
    render: Literal["auto", "static", "js"] = "auto",
    follow_links: bool = False,
    max_depth: int = 1,
    max_pages: int = 10,
    same_host_only: bool = True,
    store: bool = True,
) -> str:
    """Crawl a URL and return extracted text and markdown.

    - render: "auto" tries static first then falls back to JS rendering.
    - follow_links: when true, performs a polite BFS up to max_depth/max_pages.
    - store: persist results in Postgres.
    """
    if follow_links:
        results = await crawl_site(
            url,
            render=render,
            max_depth=max_depth,
            max_pages=max_pages,
            same_host_only=same_host_only,
        )
    else:
        results = [await crawl_one(url, render=render, check_robots=True)]

    out = await _store(results) if store else list(results)
    return json.dumps(
        {"count": len(out), "pages": [_strip_html(p) for p in out]}, default=str
    )


@mcp.tool()
async def get_page(url: str) -> str:
    """Retrieve a previously crawled page by URL."""
    row = await db.get_page_by_url(url)
    if row is None:
        return json.dumps({"error": "not found"})
    return json.dumps(_strip_html(row), default=str)


@mcp.tool()
async def list_recent(limit: int = 20) -> str:
    """List recently crawled pages."""
    rows = await db.list_pages(limit=limit)
    return json.dumps(rows, default=str)


@mcp.tool()
async def search(query: str, limit: int = 20) -> str:
    """Search previously crawled pages by URL, title, or text content."""
    rows = await db.search_pages(query, limit=limit)
    return json.dumps(rows, default=str)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
