"""Shared, pooled httpx clients.

Previously every fetch built a brand-new client, forcing a fresh TCP+TLS
handshake per page. Here we keep long-lived, connection-pooled clients (one per
proxy, plus a default), enable HTTP/2 when available, and reuse them across
requests — a big latency win on multi-page crawls and a requirement for looking
like a real browser.
"""
from __future__ import annotations

import httpx

from . import ssrf
from .config import settings

# Whether the optional HTTP/2 stack (`h2`) is importable. Probed once.
try:  # pragma: no cover - trivial import probe
    import h2  # noqa: F401

    _HTTP2_AVAILABLE = True
except Exception:  # noqa: BLE001
    _HTTP2_AVAILABLE = False


_clients: dict[str | None, httpx.AsyncClient] = {}


def _limits() -> httpx.Limits:
    return httpx.Limits(
        max_keepalive_connections=settings.max_keepalive_connections,
        max_connections=settings.max_connections,
    )


def _build(proxy: str | None) -> httpx.AsyncClient:
    http2 = settings.http2 and _HTTP2_AVAILABLE
    common = dict(
        follow_redirects=False,
        http2=http2,
        limits=_limits(),
        timeout=httpx.Timeout(settings.request_timeout),
    )
    if proxy:
        # Proxied connections can't use our IP-pinned backend (the proxy does the
        # DNS), so SSRF relies on per-request validation here.
        return httpx.AsyncClient(proxy=proxy, **common)
    # No proxy: pin connections to validated IPs (closes DNS-rebinding window).
    return ssrf.build_async_client(**common)


def get_client(proxy: str | None = None) -> httpx.AsyncClient:
    """Return a pooled client for the given proxy (None = direct)."""
    client = _clients.get(proxy)
    if client is None or client.is_closed:
        client = _build(proxy)
        _clients[proxy] = client
    return client


async def aclose_all() -> None:
    """Close every pooled client. Call on shutdown."""
    for client in list(_clients.values()):
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _clients.clear()
