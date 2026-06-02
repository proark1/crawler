from __future__ import annotations

import asyncio

import asyncpg
import httpx
import pytest

from app import api, crawler, db
from app.crawler import CrawlResult


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=api.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _patch_crawl(monkeypatch):
    async def fake_crawl_one(url, render="auto"):
        return CrawlResult(
            url=url, final_url=url, status=200, title="T", text="hi",
            links=[], metadata={}, render_mode="static", error=None, html="<html></html>",
        )

    async def fake_upsert(page):
        page = dict(page)
        page["id"] = 1
        return page

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(db, "upsert_page", fake_upsert)


@pytest.mark.asyncio
async def test_ready_endpoint(monkeypatch):
    async def up():
        return True

    async def down():
        return False

    monkeypatch.setattr(db, "ping", up)
    async with _client() as c:
        assert (await c.get("/ready")).status_code == 200
    monkeypatch.setattr(db, "ping", down)
    async with _client() as c:
        r = await c.get("/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "unready"


@pytest.mark.asyncio
async def test_v1_prefix_routes_same_handlers(monkeypatch):
    async def ok():
        return True

    monkeypatch.setattr(db, "ping", ok)
    async with _client() as c:
        r = await c.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_db_error_returns_503(monkeypatch):
    async def boom():
        raise asyncpg.PostgresError("connection reset")

    monkeypatch.setattr(db, "stats", boom)
    async with _client() as c:
        r = await c.get("/stats")
    assert r.status_code == 503
    assert r.json()["detail"] == "Database unavailable"


@pytest.mark.asyncio
async def test_pool_timeout_returns_503(monkeypatch):
    async def slow():
        raise TimeoutError()

    monkeypatch.setattr(db, "stats", slow)
    async with _client() as c:
        r = await c.get("/stats")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_batch_crawl_creates_a_job_per_url(monkeypatch):
    _patch_crawl(monkeypatch)
    async with _client() as c:
        r = await c.post(
            "/crawl/batch",
            json={"urls": ["https://a.com", "https://b.com"], "follow_links": False},
        )
    assert r.status_code == 202
    jobs_out = r.json()["jobs"]
    assert len(jobs_out) == 2
    assert {j["url"].rstrip("/") for j in jobs_out} == {"https://a.com", "https://b.com"}
    assert all(j["job_id"] for j in jobs_out)


@pytest.mark.asyncio
async def test_idempotency_key_returns_same_job(monkeypatch):
    _patch_crawl(monkeypatch)
    headers = {"Idempotency-Key": "abc-123"}
    async with _client() as c:
        r1 = await c.post("/crawl/jobs", json={"url": "https://ex.com"}, headers=headers)
        r2 = await c.post("/crawl/jobs", json={"url": "https://ex.com"}, headers=headers)
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_cancel_unknown_job_404():
    async with _client() as c:
        r = await c.delete("/crawl/jobs/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_finished_job_409(monkeypatch):
    _patch_crawl(monkeypatch)
    async with _client() as c:
        r = await c.post("/crawl/jobs", json={"url": "https://ex.com"})
        job_id = r.json()["id"]
        for _ in range(50):
            if (await c.get(f"/crawl/jobs/{job_id}")).json()["status"] == "done":
                break
            await asyncio.sleep(0.02)
        cancelled = await c.delete(f"/crawl/jobs/{job_id}")
    assert cancelled.status_code == 409


@pytest.mark.asyncio
async def test_ready_is_exempt_from_rate_limit(monkeypatch):
    """Infra probes hit /ready constantly; the limiter must never 429 it."""
    async def up():
        return True

    monkeypatch.setattr(db, "ping", up)
    monkeypatch.setattr(api.settings, "rate_limit_per_minute", 1)
    async with _client() as c:
        for _ in range(3):  # well past the limit of 1
            assert (await c.get("/ready")).status_code == 200
            # Trailing slash must be exempt too (orchestrators may add one); the
            # limiter would otherwise 429 the 2nd hit. Anything but 429 == exempt.
            assert (await c.get("/ready/")).status_code != 429


@pytest.mark.asyncio
async def test_job_rejects_private_webhook_url(monkeypatch):
    """A webhook_url resolving to an internal address is rejected at submit (SSRF)."""
    monkeypatch.setattr(api.settings, "block_private_addresses", True)
    monkeypatch.setattr(api.settings, "ssrf_allowlist", "")
    async with _client() as c:
        r = await c.post(
            "/crawl/jobs",
            json={"url": "https://example.com", "webhook_url": "http://127.0.0.1:9/hook"},
        )
    assert r.status_code == 422
    assert "webhook_url" in r.text
