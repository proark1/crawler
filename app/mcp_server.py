"""MCP server exposing the crawler over stdio.

Tools share the same orchestration as the REST API (`app/service.py`), so they
get identical SSRF protection, robots.txt handling, conditional re-crawl, and
persistence. Returned pages include extracted text, Markdown, links, and
structured metadata (OpenGraph/JSON-LD/canonical/language/author); raw HTML is
omitted from tool output but can be fetched with `get_page_html`.

Run locally:
    python -m app.mcp_server
"""
from __future__ import annotations

import json
from typing import Literal

from mcp.server.fastmcp import FastMCP

from . import db, service

mcp = FastMCP("crawler")


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
    """Crawl a URL and return extracted content as JSON.

    - render: "auto" tries a static fetch first and falls back to headless-browser
      JS rendering only when the page looks empty; "static" or "js" force one mode.
    - follow_links: when true, performs a same-host BFS up to max_depth/max_pages.
    - same_host_only: restrict the BFS to the start host (apex/www treated alike).
    - store: persist results in Postgres (enables conditional re-crawl next time).

    Private/internal addresses and disallowed robots paths are refused. Each page
    includes url, final_url, status, title, text, markdown, links, metadata,
    render_mode, etag, last_modified, content_hash, and error.
    """
    pages = await service.run_crawl(
        url=url,
        render=render,
        follow_links=follow_links,
        max_depth=max_depth,
        max_pages=max_pages,
        same_host_only=same_host_only,
        store=store,
    )
    return json.dumps({"count": len(pages), "pages": pages}, default=str)


@mcp.tool()
async def get_page(url: str) -> str:
    """Retrieve a previously crawled page by URL (text, markdown, links, metadata)."""
    row = await db.get_page_by_url(url)
    if row is None:
        return json.dumps({"error": "not found"})
    row.pop("html", None)
    return json.dumps(row, default=str)


@mcp.tool()
async def get_page_html(url: str) -> str:
    """Retrieve the stored raw HTML for a previously crawled page by URL."""
    row = await db.get_page_by_url(url)
    if row is None:
        return json.dumps({"error": "not found"})
    html = await db.get_page_html(int(row["id"]))
    if html is None:
        return json.dumps({"error": "no stored HTML"})
    return json.dumps({"html": html})


@mcp.tool()
async def list_recent(limit: int = 20) -> str:
    """List recently crawled pages (most recent first)."""
    rows = await db.list_pages(limit=limit)
    return json.dumps(rows, default=str)


@mcp.tool()
async def search(query: str, limit: int = 20) -> str:
    """Search previously crawled pages by URL, title, or text content (full-text ranked)."""
    rows = await db.search_pages(query, limit=limit)
    return json.dumps(rows, default=str)


@mcp.tool()
async def recent_jobs(limit: int = 20) -> str:
    """List recent background crawl jobs and their status."""
    rows = await db.list_jobs(limit=limit)
    return json.dumps(rows, default=str)


@mcp.tool()
async def stats() -> str:
    """Return index statistics (total stored pages)."""
    total = await db.count_pages()
    return json.dumps({"pages": total})


@mcp.tool()
async def delete_page(url: str) -> str:
    """Delete a previously crawled page by URL."""
    row = await db.get_page_by_url(url)
    if row is None:
        return json.dumps({"deleted": False, "reason": "not found"})
    deleted = await db.delete_page(int(row["id"]))
    return json.dumps({"deleted": deleted})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
