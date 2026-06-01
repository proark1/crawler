from __future__ import annotations

import asyncio

import httpx
import pytest

from app import api, db
from app.crawler import CrawlResult


def _client() -> httpx.AsyncClient:
    # ASGITransport does not run lifespan, so the DB pool is never created.
    transport = httpx.ASGITransport(app=api.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health_reports_db_status(monkeypatch):
    async def ok():
        return True

    monkeypatch.setattr(db, "ping", ok)
    async with _client() as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": True}


@pytest.mark.asyncio
async def test_health_degraded_when_db_down(monkeypatch):
    async def down():
        return False

    monkeypatch.setattr(db, "ping", down)
    async with _client() as c:
        r = await c.get("/health")
    assert r.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_crawl_single_page(monkeypatch):
    async def fake_crawl_one(url, render="auto"):
        return CrawlResult(
            url=url, final_url=url, status=200, title="T", text="hi",
            links=[], metadata={}, render_mode="static", error=None, html="<html></html>",
        )

    async def fake_upsert(page):
        page = dict(page)
        page["id"] = 1
        return page

    monkeypatch.setattr(api, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(db, "upsert_page", fake_upsert)

    async with _client() as c:
        r = await c.post("/crawl", json={"url": "https://ex.com", "follow_links": False})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["pages"][0]["title"] == "T"
    # raw html must be stripped from the response
    assert "html" not in body["pages"][0]


@pytest.mark.asyncio
async def test_crawl_job_lifecycle(monkeypatch):
    async def fake_crawl_one(url, render="auto"):
        return CrawlResult(
            url=url, final_url=url, status=200, title="J", text="x",
            links=[], metadata={}, render_mode="static", error=None, html="h",
        )

    async def fake_upsert(page):
        page = dict(page)
        page["id"] = 7
        return page

    monkeypatch.setattr(api, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(db, "upsert_page", fake_upsert)

    async with _client() as c:
        r = await c.post("/crawl/jobs", json={"url": "https://ex.com"})
        assert r.status_code == 202
        job_id = r.json()["id"]

        # poll until done
        for _ in range(50):
            jr = await c.get(f"/crawl/jobs/{job_id}")
            if jr.json()["status"] == "done":
                break
            await asyncio.sleep(0.02)
        data = jr.json()
    assert data["status"] == "done"
    assert data["count"] == 1
    assert data["pages"][0]["title"] == "J"


@pytest.mark.asyncio
async def test_get_unknown_job_404():
    async with _client() as c:
        r = await c.get("/crawl/jobs/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_pages_sets_total_header(monkeypatch):
    async def fake_list(limit, offset):
        return [
            {"id": 1, "url": "https://ex.com", "render_mode": "static"},
        ]

    async def fake_count():
        return 42

    monkeypatch.setattr(db, "list_pages", fake_list)
    monkeypatch.setattr(db, "count_pages", fake_count)

    async with _client() as c:
        r = await c.get("/pages")
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "42"
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_delete_page(monkeypatch):
    async def fake_delete(page_id):
        return page_id == 5

    monkeypatch.setattr(db, "delete_page", fake_delete)

    async with _client() as c:
        ok = await c.delete("/pages/5")
        missing = await c.delete("/pages/6")
    assert ok.status_code == 204
    assert missing.status_code == 404
