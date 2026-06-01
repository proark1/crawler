from __future__ import annotations

from datetime import UTC

import pytest

from app import crawler, db, service
from app.config import settings


@pytest.mark.asyncio
async def test_run_crawl_single_stores_and_strips_html(monkeypatch):
    async def fake_crawl_one(url, render="auto", cached=None):
        return crawler.CrawlResult(
            url=url, render_mode="static", title="T", text="hi",
            html="<html></html>", links=[], error=None,
        )

    async def fake_lookup(url):
        return None  # nothing stored yet

    async def fake_upsert(page):
        out = dict(page)
        out["id"] = 1
        return out

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(db, "get_page_by_url", fake_lookup)
    monkeypatch.setattr(db, "upsert_page", fake_upsert)

    pages = await service.run_crawl(url="https://ex.com", store=True)
    assert len(pages) == 1
    assert pages[0]["id"] == 1
    assert "html" not in pages[0]  # raw HTML stripped from output


@pytest.mark.asyncio
async def test_run_crawl_serves_fresh_from_cache(monkeypatch):
    from datetime import datetime

    fetched = datetime.now(UTC).isoformat()

    async def fake_lookup(url):
        return {"url": url, "render_mode": "static", "title": "cached",
                "fetched_at": fetched, "error": None}

    async def boom(*a, **k):
        raise AssertionError("should not crawl a fresh cached page")

    monkeypatch.setattr(db, "get_page_by_url", fake_lookup)
    monkeypatch.setattr(crawler, "crawl_one", boom)
    monkeypatch.setattr(settings, "recrawl_max_age", 300.0)

    pages = await service.run_crawl(url="https://ex.com", store=True)
    assert pages[0]["from_cache"] is True
    assert pages[0]["title"] == "cached"
