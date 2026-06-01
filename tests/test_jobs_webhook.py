from __future__ import annotations

import hashlib
import hmac

import pytest

from app import jobs
from app.config import settings


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.request = None


class _FakeClient:
    """Records POST calls and returns queued responses."""

    calls: list[dict] = []
    responses: list[int] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, content=None, headers=None):
        type(self).calls.append({"url": url, "content": content, "headers": headers})
        status = type(self).responses.pop(0) if type(self).responses else 200
        return _FakeResp(status)


@pytest.fixture(autouse=True)
def _reset():
    _FakeClient.calls = []
    _FakeClient.responses = []
    yield


def _job(url="https://hook.example/cb"):
    j = jobs.Job(id="j1", status="done", webhook_url=url)
    j.pages = [{"url": "https://x"}]
    return j


@pytest.mark.asyncio
async def test_webhook_signed_when_secret_set(monkeypatch):
    monkeypatch.setattr(jobs.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")
    await jobs.fire_webhook(_job())
    assert len(_FakeClient.calls) == 1
    body = _FakeClient.calls[0]["content"]
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert _FakeClient.calls[0]["headers"]["X-Crawler-Signature"] == expected


@pytest.mark.asyncio
async def test_webhook_retries_on_5xx(monkeypatch):
    monkeypatch.setattr(jobs.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "webhook_secret", "")
    monkeypatch.setattr(settings, "webhook_retries", 3)
    monkeypatch.setattr(jobs.asyncio, "sleep", lambda *_a, **_k: _noop())
    _FakeClient.responses = [500, 503, 200]  # succeed on third attempt
    await jobs.fire_webhook(_job())
    assert len(_FakeClient.calls) == 3


@pytest.mark.asyncio
async def test_webhook_no_url_is_noop(monkeypatch):
    monkeypatch.setattr(jobs.httpx, "AsyncClient", _FakeClient)
    j = jobs.Job(id="j2", status="done", webhook_url=None)
    await jobs.fire_webhook(j)
    assert _FakeClient.calls == []


async def _noop():
    return None
