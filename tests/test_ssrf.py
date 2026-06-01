from __future__ import annotations

import pytest

from app import ssrf
from app.config import settings


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings, "block_private_addresses", True)
    monkeypatch.setattr(settings, "ssrf_allowlist", "")


def test_ip_is_public_classification():
    assert ssrf._ip_is_public("8.8.8.8")
    assert not ssrf._ip_is_public("127.0.0.1")
    assert not ssrf._ip_is_public("10.0.0.5")
    assert not ssrf._ip_is_public("169.254.169.254")  # cloud metadata
    assert not ssrf._ip_is_public("192.168.1.1")
    assert not ssrf._ip_is_public("::1")


@pytest.mark.asyncio
async def test_blocks_literal_private_ip():
    with pytest.raises(ssrf.BlockedAddressError):
        await ssrf.assert_url_allowed("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ssrf.BlockedAddressError):
        await ssrf.assert_url_allowed("http://127.0.0.1:8000/")


@pytest.mark.asyncio
async def test_blocks_non_http_scheme():
    with pytest.raises(ssrf.BlockedAddressError):
        await ssrf.assert_url_allowed("file:///etc/passwd")


@pytest.mark.asyncio
async def test_allows_public_resolved_host(monkeypatch):
    async def fake_resolve(host):
        return ["93.184.216.34"]  # example.com, public

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    await ssrf.assert_url_allowed("https://example.com/page")  # no raise


@pytest.mark.asyncio
async def test_blocks_host_resolving_to_private(monkeypatch):
    async def fake_resolve(host):
        return ["10.1.2.3"]

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    with pytest.raises(ssrf.BlockedAddressError):
        await ssrf.assert_url_allowed("https://sneaky.internal.example/")


@pytest.mark.asyncio
async def test_allowlist_bypasses_check():
    settings.ssrf_allowlist = "localhost"
    try:
        await ssrf.assert_url_allowed("http://localhost:8000/")  # allowlisted
    finally:
        settings.ssrf_allowlist = ""


@pytest.mark.asyncio
async def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "block_private_addresses", False)
    await ssrf.assert_url_allowed("http://127.0.0.1/")  # no raise when disabled
