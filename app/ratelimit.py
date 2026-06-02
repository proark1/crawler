"""Tiny in-memory per-client rate limiter (fixed-window).

Bounds abusive bursts without adding a Redis dependency. State is per-process,
which is fine for the single-instance deployment; behind multiple instances it
becomes a per-instance limit. Disabled when rate_limit_per_minute <= 0.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

_WINDOW = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._hits: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    def _client_key(self, request: Request) -> str:
        # Prefer the API key (per-tenant), else the peer IP.
        key = request.headers.get("x-api-key")
        if key:
            return f"key:{key}"
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        limit = settings.rate_limit_per_minute
        # Never rate-limit infra probes/scrapes: orchestrators hit /health and
        # /ready frequently from one source, and Prometheus polls /metrics.
        # rstrip the path so a trailing slash (/ready/) is still exempted.
        if limit <= 0 or request.url.path.rstrip("/") in ("/health", "/ready", "/metrics"):
            return await call_next(request)

        now = time.monotonic()
        key = self._client_key(request)
        window_start, count = self._hits[key]
        if now - window_start >= _WINDOW:
            window_start, count = now, 0
        count += 1
        self._hits[key] = (window_start, count)

        # Bound memory: drop entries whose window has fully expired once the map
        # grows large, so a flood of unique IPs/keys can't leak indefinitely.
        if len(self._hits) > 10_000:
            self._hits = defaultdict(
                lambda: (0.0, 0),
                {k: v for k, v in self._hits.items() if now - v[0] < _WINDOW},
            )

        if count > limit:
            retry_after = max(1, int(_WINDOW - (now - window_start)))
            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
