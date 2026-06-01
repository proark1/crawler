import pytest
from fastapi.testclient import TestClient

from app import api, db
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    async def noop(*a, **k):
        return None

    async def ping():
        return True

    monkeypatch.setattr(db, "init_pool", noop)
    monkeypatch.setattr(db, "close_pool", noop)
    monkeypatch.setattr(db, "ping", ping)
    monkeypatch.setattr(api.jobs, "shutdown", noop)
    monkeypatch.setattr(settings, "api_key", "")  # auth disabled by default
    with TestClient(api.app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True}


def test_metrics(client):
    client.get("/health")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "crawler_requests_total" in r.text


def test_crawl_single(client, monkeypatch):
    async def fake_crawl_one(url, render="auto", check_robots=False):
        return {"url": url, "final_url": url, "status": 200, "title": "T", "text": "body",
                "markdown": "**body**", "links": [], "metadata": {}, "render_mode": "static",
                "error": None, "html": "<html></html>"}

    async def fake_upsert(page):
        return {**page, "id": 1, "fetched_at": "2026-01-01T00:00:00+00:00"}

    monkeypatch.setattr(api, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(db, "upsert_page", fake_upsert)

    r = client.post("/crawl", json={"url": "https://example.com", "store": True})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["pages"][0]["markdown"] == "**body**"
    assert "html" not in data["pages"][0]


def test_crawl_partial_store_failure(client, monkeypatch):
    async def fake_crawl_one(url, render="auto", check_robots=False):
        return {"url": url, "render_mode": "static", "metadata": {}, "links": [],
                "status": 200, "error": None}

    async def boom(page):
        raise RuntimeError("db down")

    monkeypatch.setattr(api, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(db, "upsert_page", boom)

    r = client.post("/crawl", json={"url": "https://example.com", "store": True})
    assert r.status_code == 200  # partial success, not a 500
    assert r.json()["pages"][0]["metadata"]["store_error"] == "db down"


def test_auth_enforced(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    assert client.get("/pages").status_code == 401
    monkeypatch.setattr(db, "list_pages", _empty)
    assert client.get("/pages", headers={"X-API-Key": "secret"}).status_code == 200


async def _empty(*a, **k):
    return []
