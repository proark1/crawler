"""SSRF protection for user-supplied crawl targets.

The service fetches arbitrary URLs on behalf of callers, so without guards a
caller could point it at internal services or the cloud metadata endpoint
(169.254.169.254) and exfiltrate secrets. We resolve each host and reject any
that maps to a private, loopback, link-local, or otherwise non-public address.
Redirects are validated hop-by-hop by the caller, since a public URL can 302 to
an internal one, and the browser context validates every subrequest too.

Known limitation (DNS rebinding): we validate the resolved IPs, but httpx and
the browser perform their own DNS resolution at connect time, leaving a small
TOCTOU window. Exploiting it requires an attacker-controlled domain with a very
low TTL plus a race between our check and the connect. Fully closing it means
pinning the connection to the validated IP while preserving TLS SNI/Host (a
custom transport); that is deliberately out of scope here. Deployments that need
that guarantee should run the crawler in a network with private ranges firewalled
off at the egress.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from .config import settings


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

    # A literal IP in the URL is checked directly; otherwise resolve all records.
    candidates: list[str]
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
            raise BlockedAddressError(
                f"{host} resolves to non-public address {ip}"
            )
