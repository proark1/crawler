"""robots.txt fetching, caching, and policy checks.

A polite crawler honors robots.txt. We fetch each host's robots file once,
cache it with a TTL, and expose can_fetch / crawl_delay. Fetch failures fail
*open* (allow) for 4xx and fail *closed* (disallow) only when robots itself is
unreachable would be too strict, so we allow on errors — matching common
crawler behavior — while still respecting an explicitly served file.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .config import settings
from .fetcher import safe_get

_CACHE_TTL = 3600.0  # seconds
_cache: dict[str, tuple[float, RobotFileParser | None]] = {}


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


async def _get_parser(url: str) -> RobotFileParser | None:
    key = urlsplit(url).netloc.lower()
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    parser: RobotFileParser | None = RobotFileParser()
    try:
        result = await safe_get(_robots_url(url))
        if result.status and 200 <= result.status < 300 and result.html is not None:
            parser.parse(result.html.splitlines())
        elif result.status and 400 <= result.status < 500:
            parser = None  # no robots / forbidden -> allow everything
        else:
            parser = None  # server error or network issue -> don't block crawling
    except Exception:  # noqa: BLE001 - never let robots break a crawl
        parser = None

    _cache[key] = (now, parser)
    return parser


async def can_fetch(url: str) -> bool:
    if not settings.respect_robots:
        return True
    parser = await _get_parser(url)
    if parser is None:
        return True
    return parser.can_fetch(settings.user_agent, url)


async def crawl_delay(url: str) -> float | None:
    if not settings.respect_robots:
        return None
    parser = await _get_parser(url)
    if parser is None:
        return None
    delay = parser.crawl_delay(settings.user_agent)
    return float(delay) if delay is not None else None


def clear_cache() -> None:
    _cache.clear()
