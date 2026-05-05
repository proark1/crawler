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
    """Crawl a URL and return extracted text.

    - render: "auto" tries static first then falls back to JS rendering.
    - follow_links: when true, performs a BFS up to max_depth/max_pages.
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
        results = [await crawl_one(url, render=render)]

    if store:
        saved_pages = await asyncio.gather(*(db.upsert_page(r) for r in results))
        out = [_strip_html(p) for p in saved_pages]
    else:
        out = [_strip_html(r) for r in results]
    return json.dumps({"count": len(out), "pages": out}, default=str)


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
