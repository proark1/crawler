"""SSRF protection for user-supplied crawl targets.

The service fetches arbitrary URLs on behalf of callers, so without guards a
caller could point it at internal services or the cloud metadata endpoint
(169.254.169.254) and exfiltrate secrets. We resolve each host and reject any
that maps to a private, loopback, link-local, or otherwise non-public address.
Redirects are validated hop-by-hop by the caller, since a public URL can 302 to
an internal one, and the browser context validates every subrequest too.

DNS rebinding (TOCTOU) mitigation: `build_async_client` returns an httpx client
whose connections are routed through our own validated resolver — the IP we
checked is the exact IP we connect to. httpcore still performs the TLS handshake
against the original hostname, so SNI and certificate verification stay correct.
This closes the window where a low-TTL attacker domain could pass validation and
then resolve to a private IP at connect time. The headless browser (Playwright)
does its own DNS, so for JS rendering we rely on per-subrequest validation; for
defence in depth, run the crawler with private ranges firewalled off at egress.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

from .config import settings

log = logging.getLogger("crawler.ssrf")


class BlockedAddressError(Exception):
    """Raised when a URL resolves to a disallowed address."""


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


# Short-TTL cache of validated resolutions, so a single request doesn't resolve
# the host twice (once to validate, once to connect) and repeat crawls of a host
# skip the lookup. Caching the *validated* IP also keeps the checked IP and the
# connected IP identical within the TTL.
_dns_cache: dict[str, tuple[float, list[str]]] = {}


async def resolve_validated(host: str) -> list[str]:
    """Resolve a host to its IPs, raising BlockedAddressError if any is non-public.

    A literal IP is checked directly. Returns the list of validated IPs.
    """
    host = host.lower()
    import time

    hit = _dns_cache.get(host)
    if hit is not None and (time.monotonic() - hit[0]) < settings.dns_cache_ttl:
        return hit[1]

    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        try:
            candidates = await _resolve(host)
        except socket.gaierror as exc:
            raise BlockedAddressError(f"cannot resolve host: {host}") from exc

    if not candidates:
        raise BlockedAddressError(f"no addresses for host: {host}")
    for ip in candidates:
        if not _ip_is_public(ip):
            raise BlockedAddressError(f"{host} resolves to non-public address {ip}")
    if settings.dns_cache_ttl > 0:
        _dns_cache[host] = (time.monotonic(), candidates)
        if len(_dns_cache) > 10_000:
            _dns_cache.clear()
    return candidates


async def assert_url_allowed(url: str) -> None:
    """Raise BlockedAddressError if the URL must not be fetched.

    No-op when SSRF protection is disabled. Hosts in the allowlist bypass the
    address check (useful for talking to a known internal service in tests).
    """
    if not settings.block_private_addresses:
        return

    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedAddressError(f"unsupported scheme: {parts.scheme!r}")

    host = (parts.hostname or "").lower()
    if not host:
        raise BlockedAddressError("missing host")
    if host in settings.ssrf_allowed_hosts:
        return

    await resolve_validated(host)


async def _connect_host(host: str) -> str:
    """Return the IP to connect to for `host` (validated), or the host unchanged
    when SSRF is disabled or the host is allowlisted."""
    if not settings.block_private_addresses:
        return host
    if host.lower() in settings.ssrf_allowed_hosts:
        return host
    ips = await resolve_validated(host)
    return ips[0]


class _PinnedBackend:
    """httpcore network backend that connects to our pre-validated IP.

    Delegates everything to the wrapped backend but rewrites the TCP target host
    to the validated IP. TLS (start_tls) is driven separately by httpcore using
    the original hostname, so SNI and certificate verification are unaffected.
    """

    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):  # type: ignore[no-untyped-def]
        ip = await _connect_host(host)
        return await self._inner.connect_tcp(
            ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await self._inner.connect_unix_socket(*args, **kwargs)

    async def sleep(self, seconds):  # type: ignore[no-untyped-def]
        return await self._inner.sleep(seconds)


def build_async_client(**kwargs) -> httpx.AsyncClient:
    """An httpx.AsyncClient that pins connections to validated IPs when SSRF is on.

    Falls back to a plain client (still protected by per-request
    `assert_url_allowed` checks) if httpcore internals aren't shaped as expected.
    """
    if not settings.block_private_addresses:
        return httpx.AsyncClient(**kwargs)
    try:
        transport = httpx.AsyncHTTPTransport(retries=0)
        pool = transport._pool  # type: ignore[attr-defined]
        pool._network_backend = _PinnedBackend(pool._network_backend)  # type: ignore[attr-defined]
        return httpx.AsyncClient(transport=transport, **kwargs)
    except Exception as exc:  # noqa: BLE001 -- never break fetching over a pinning hiccup
        log.warning("IP-pinned transport unavailable, using plain client: %s", exc)
        return httpx.AsyncClient(**kwargs)
