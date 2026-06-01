from __future__ import annotations

import pytest

from app import antibot
from app.antibot import Tier
from app.config import settings

# --------------------------------------------------------------------------- #
# Headers                                                                     #
# --------------------------------------------------------------------------- #


def test_browser_headers_realistic_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "antibot_enabled", True)
    h = antibot.browser_headers("https://example.com/p", referer="https://example.com/")
    assert "Chrome/" in h["User-Agent"]
    assert h["sec-ch-ua-platform"] == '"Windows"'
    assert h["Sec-Fetch-Mode"] == "navigate"
    assert h["Referer"] == "https://example.com/"
    # Host/Accept-Encoding must not be set manually.
    assert "Host" not in h and "Accept-Encoding" not in h


def test_browser_headers_minimal_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "antibot_enabled", False)
    h = antibot.browser_headers("https://example.com/")
    assert set(h) == {"User-Agent", "Accept"}


# --------------------------------------------------------------------------- #
# Block detection                                                             #
# --------------------------------------------------------------------------- #


def test_detect_clean_page_is_not_blocked():
    sig = antibot.detect_block(200, {"server": "nginx"}, "<html><body>hello</body></html>")
    assert not sig.blocked


@pytest.mark.parametrize(
    "status,headers,html,vendor",
    [
        (403, {"server": "cloudflare"}, "x", "cloudflare"),
        (200, {}, "<title>Just a moment...</title>", "cloudflare"),
        (200, {"cf-mitigated": "challenge"}, "x", "cloudflare"),
        (200, {}, "please enable js geo.captcha-delivery.com", "datadome"),
        (200, {}, "<div id='px-captcha'></div>", "perimeterx"),
        (200, {}, "Request unsuccessful. Incapsula incident", "imperva"),
        (200, {}, "<div class='h-captcha'></div>", "hcaptcha"),
        (429, {}, "slow down", "generic"),
    ],
)
def test_detect_block_vendors(status, headers, html, vendor):
    sig = antibot.detect_block(status, headers, html)
    assert sig.blocked
    assert sig.vendor == vendor


def test_turnstile_marks_needs_solver():
    sig = antibot.detect_block(403, {"server": "cloudflare"}, "cf-turnstile")
    assert sig.needs_browser and sig.needs_solver


# --------------------------------------------------------------------------- #
# Domain profile memory                                                       #
# --------------------------------------------------------------------------- #


def test_profile_record_block_raises_tier():
    store = antibot.DomainProfileStore(max_size=10)
    assert store.suggested_tier("https://x.com/a") == int(Tier.STATIC)
    store.record_block("https://x.com/a", int(Tier.STATIC), "cloudflare")
    assert store.suggested_tier("https://www.x.com/b") == int(Tier.IMPERSONATE)


def test_profile_record_success_remembers_min_tier():
    store = antibot.DomainProfileStore(max_size=10)
    store.record_block("https://y.com", int(Tier.STATIC), "datadome")  # min -> 1
    store.record_success("https://y.com", int(Tier.BROWSER))
    store.record_success("https://y.com", int(Tier.IMPERSONATE))
    assert store.suggested_tier("https://y.com") == int(Tier.IMPERSONATE)


def test_profile_store_evicts_lru():
    store = antibot.DomainProfileStore(max_size=2)
    store.get("https://a.com")
    store.get("https://b.com")
    store.get("https://c.com")  # evicts a.com
    assert len(store._data) == 2
    assert "a.com" not in store._data


# --------------------------------------------------------------------------- #
# Proxy rotation                                                              #
# --------------------------------------------------------------------------- #


def test_proxy_none_without_pool(monkeypatch):
    monkeypatch.setattr(settings, "proxy_pool", "")
    monkeypatch.setattr(settings, "proxy_url", "")
    rot = antibot.ProxyRotator()
    assert rot.pick("x.com", int(Tier.BROWSER)) is None


def test_proxy_sticky_and_rotate(monkeypatch):
    monkeypatch.setattr(settings, "proxy_pool", "http://p1,http://p2")
    monkeypatch.setattr(settings, "proxy_url", "")
    monkeypatch.setattr(settings, "proxy_from_tier", int(Tier.IMPERSONATE))
    rot = antibot.ProxyRotator()
    # Tier below threshold -> no proxy.
    assert rot.pick("x.com", int(Tier.STATIC)) is None
    first = rot.pick("x.com", int(Tier.IMPERSONATE))
    assert first in ("http://p1", "http://p2")
    assert rot.pick("x.com", int(Tier.IMPERSONATE)) == first  # sticky
    rot.rotate("x.com")
    assert rot.pick("x.com", int(Tier.IMPERSONATE)) in ("http://p1", "http://p2")
