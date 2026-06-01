from __future__ import annotations

import pytest

from app import solver
from app.config import settings


@pytest.mark.asyncio
async def test_solve_unavailable_without_url(monkeypatch):
    monkeypatch.setattr(settings, "flaresolverr_url", "")
    with pytest.raises(solver.SolverUnavailable):
        await solver.solve("https://example.com")


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json):
        assert url.endswith("/v1")
        assert json["cmd"] == "request.get"
        return _FakeResp(self._payload)


@pytest.mark.asyncio
async def test_solve_parses_flaresolverr_response(monkeypatch):
    monkeypatch.setattr(settings, "flaresolverr_url", "http://flaresolverr:8191")
    payload = {
        "status": "ok",
        "solution": {
            "status": 200,
            "url": "https://example.com/",
            "response": "<html>solved</html>",
            "cookies": [{"name": "cf_clearance", "value": "abc"}],
        },
    }
    monkeypatch.setattr(solver.httpx, "AsyncClient", lambda **k: _FakeClient(payload))

    res = await solver.solve("https://example.com/")
    assert res.status == 200
    assert "solved" in res.html
    assert res.cookies[0]["name"] == "cf_clearance"


@pytest.mark.asyncio
async def test_solve_raises_on_error_status(monkeypatch):
    import httpx

    monkeypatch.setattr(settings, "flaresolverr_url", "http://flaresolverr:8191")
    monkeypatch.setattr(
        solver.httpx, "AsyncClient", lambda **k: _FakeClient({"status": "error", "message": "boom"})
    )
    with pytest.raises(httpx.HTTPError):
        await solver.solve("https://example.com/")
