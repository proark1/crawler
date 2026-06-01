"""Anti-bot toolkit: realistic headers, block detection, per-domain strategy
memory, and proxy rotation.

This module is pure logic (no I/O), so it is fully unit-testable offline and is
shared by every fetch engine. The crawler escalates through engines
(static httpx -> curl_cffi impersonation -> headless browser -> solver) based on
what `BlockDetector` reports and what worked for a domain last time.
"""
from __future__ import annotations

import itertools
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import IntEnum
from urllib.parse import urlparse

from .config import settings


class Tier(IntEnum):
    STATIC = 0       # plain httpx
    IMPERSONATE = 1  # curl_cffi browser TLS/HTTP2 impersonation
    BROWSER = 2      # headless (stealth) browser
    SOLVER = 3       # challenge solver (FlareSolverr / CAPTCHA service)


# A realistic, internally consistent desktop Chrome profile. The UA, client
# hints, and curl_cffi impersonation target must all agree or detectors notice.
_CHROME_VERSION = "124"
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{_CHROME_VERSION}.0.0.0 Safari/537.36"
)


def browser_headers(url: str, referer: str | None = None) -> dict[str, str]:
    """Browser-like request headers in a browser-like order.

    Used when anti-bot is enabled; falls back to a minimal header set otherwise.
    """
    if not settings.antibot_enabled:
        return {"User-Agent": settings.user_agent, "Accept": "text/html,*/*;q=0.8"}

    # Note: Host and Accept-Encoding are intentionally omitted — the HTTP client
    # sets Host from the URL and negotiates only the content-encodings it can
    # actually decode (advertising br without a brotli decoder breaks responses).
    headers: dict[str, str] = {
        "User-Agent": _CHROME_UA,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": settings.accept_language,
        "sec-ch-ua": f'"Chromium";v="{_CHROME_VERSION}", "Google Chrome";v="{_CHROME_VERSION}", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


# --------------------------------------------------------------------------- #
# Block detection                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class BlockSignal:
    blocked: bool
    vendor: str | None = None
    reason: str | None = None
    needs_browser: bool = False   # an interactive/JS challenge is present
    needs_solver: bool = False    # a CAPTCHA/managed challenge needs solving

    @classmethod
    def ok(cls) -> BlockSignal:
        return cls(blocked=False)


# (substring, vendor, needs_browser, needs_solver) — matched case-insensitively.
_BODY_SIGNS: list[tuple[str, str, bool, bool]] = [
    ("just a moment", "cloudflare", True, True),
    ("cf-chl", "cloudflare", True, True),
    ("challenge-platform", "cloudflare", True, True),
    ("checking your browser", "cloudflare", True, True),
    ("attention required! | cloudflare", "cloudflare", True, True),
    ("cf-turnstile", "cloudflare", True, True),
    ("/cdn-cgi/challenge", "cloudflare", True, True),
    ("geo.captcha-delivery.com", "datadome", True, True),
    ("datadome", "datadome", True, True),
    ("px-captcha", "perimeterx", True, True),
    ("perimeterx", "perimeterx", True, True),
    ("access to this page has been denied", "perimeterx", True, True),
    ("_incapsula_resource", "imperva", True, True),
    ("request unsuccessful. incapsula", "imperva", True, True),
    ("akamaighost", "akamai", False, False),
    ("errors.edgesuite.net", "akamai", False, False),
    ("g-recaptcha", "recaptcha", True, True),
    ("h-captcha", "hcaptcha", True, True),
    ("hcaptcha.com", "hcaptcha", True, True),
]


def detect_block(
    status: int | None,
    headers: dict[str, str] | None,
    html: str | None,
) -> BlockSignal:
    """Classify whether a response is a bot-protection block/challenge."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    body = (html or "")[:20000].lower()  # cap scan cost
    server = headers.get("server", "").lower()
    cf_mitigated = headers.get("cf-mitigated", "").lower()

    # Header-driven Cloudflare managed challenge.
    if cf_mitigated == "challenge" or ("cloudflare" in server and status in (403, 429, 503)):
        return BlockSignal(True, "cloudflare", "cf challenge", needs_browser=True, needs_solver=True)

    for sign, vendor, needs_browser, needs_solver in _BODY_SIGNS:
        if sign in body:
            return BlockSignal(
                True, vendor, f"matched {sign!r}",
                needs_browser=needs_browser, needs_solver=needs_solver,
            )

    # Generic status-based blocks (no vendor fingerprint).
    if status in (401, 403, 429):
        return BlockSignal(True, "generic", f"status {status}", needs_browser=True)
    if status == 503 and "cloudflare" in server:
        return BlockSignal(True, "cloudflare", "status 503", needs_browser=True, needs_solver=True)

    return BlockSignal.ok()


# --------------------------------------------------------------------------- #
# Per-domain strategy memory                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class DomainProfile:
    host: str
    min_tier: int = int(Tier.STATIC)
    successes: int = 0
    blocks: int = 0
    last_vendor: str | None = None
    last_block_at: float = 0.0
    updated_at: float = field(default_factory=time.time)


class DomainProfileStore:
    """Bounded LRU of what worked per host, so we don't re-escalate every time."""

    def __init__(self, max_size: int | None = None) -> None:
        self._max = max_size or settings.domain_profile_size
        self._data: OrderedDict[str, DomainProfile] = OrderedDict()

    def _host(self, url_or_host: str) -> str:
        host = urlparse(url_or_host).hostname or url_or_host
        return host.lower().removeprefix("www.")

    def get(self, url_or_host: str) -> DomainProfile:
        host = self._host(url_or_host)
        prof = self._data.get(host)
        if prof is None:
            prof = DomainProfile(host=host)
            self._data[host] = prof
        self._data.move_to_end(host)
        self._evict()
        return prof

    def suggested_tier(self, url_or_host: str) -> int:
        return self.get(url_or_host).min_tier

    def record_success(self, url_or_host: str, tier: int) -> None:
        prof = self.get(url_or_host)
        prof.successes += 1
        # Remember the lowest tier that actually worked.
        prof.min_tier = min(prof.min_tier, tier) if prof.successes > 1 else tier
        prof.updated_at = time.time()

    def record_block(self, url_or_host: str, tier: int, vendor: str | None) -> None:
        prof = self.get(url_or_host)
        prof.blocks += 1
        prof.last_vendor = vendor
        prof.last_block_at = time.time()
        # Next time, start at least one tier higher (capped at SOLVER).
        prof.min_tier = min(int(Tier.SOLVER), max(prof.min_tier, tier + 1))
        prof.updated_at = prof.last_block_at

    def _evict(self) -> None:
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def snapshot(self, limit: int = 200) -> list[dict]:
        """Most-recently-updated domain profiles, for observability."""
        items = sorted(self._data.values(), key=lambda p: p.updated_at, reverse=True)
        out = []
        for p in items[:limit]:
            out.append({
                "host": p.host,
                "min_tier": p.min_tier,
                "engine": Tier(p.min_tier).name.lower(),
                "successes": p.successes,
                "blocks": p.blocks,
                "last_vendor": p.last_vendor,
                "last_block_at": p.last_block_at or None,
            })
        return out


profiles = DomainProfileStore()


# --------------------------------------------------------------------------- #
# Proxy rotation                                                              #
# --------------------------------------------------------------------------- #


class ProxyRotator:
    """Sticky-per-host proxy selection with rotate-on-block."""

    def __init__(self) -> None:
        self._sticky: dict[str, str] = {}
        self._cycle = None

    def _pool(self) -> list[str]:
        return settings.proxies

    def pick(self, host: str, tier: int) -> str | None:
        pool = self._pool()
        if not pool or tier < settings.proxy_from_tier:
            return None
        if host not in self._sticky:
            if self._cycle is None:
                self._cycle = itertools.cycle(pool)
            self._sticky[host] = next(self._cycle)
        return self._sticky[host]

    def rotate(self, host: str) -> None:
        """Drop the sticky proxy for a host so the next pick advances."""
        self._sticky.pop(host, None)


proxies = ProxyRotator()
