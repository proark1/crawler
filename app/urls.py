"""URL normalization and SSRF-safety helpers."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import parse_qsl, urldefrag, urlencode, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize(url: str) -> str:
    """Canonicalize a URL so equivalent links dedupe to one key.

    - lowercase scheme + host
    - drop the fragment
    - drop the default port
    - sort query parameters
    - strip a trailing slash from non-root paths
    """
    url, _ = urldefrag(url.strip())
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()

    netloc = host
    if parts.port is not None and parts.port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"
    # Preserve userinfo if present (rare for crawls, but don't silently drop it).
    if parts.username:
        auth = parts.username
        if parts.password:
            auth += f":{parts.password}"
        netloc = f"{auth}@{netloc}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def same_host(a: str, b: str) -> bool:
    return (urlsplit(a).hostname or "").lower() == (urlsplit(b).hostname or "").lower()


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class UnsafeURLError(ValueError):
    """Raised when a URL targets a disallowed (e.g. private/internal) address."""


def _is_public_ip(ip: str) -> bool:
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


def assert_safe_url(url: str, *, block_private: bool = True) -> None:
    """Validate scheme and (optionally) that the host resolves to a public IP.

    Guards against SSRF into cloud metadata endpoints, localhost, and RFC-1918
    ranges. Raises UnsafeURLError on violation.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"unsupported scheme: {parts.scheme or '(none)'!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("missing host")
    if not block_private:
        return

    # If the host is already a literal IP, check it directly.
    try:
        ipaddress.ip_address(host)
        literals = [host]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parts.port or _DEFAULT_PORTS.get(parts.scheme, 80))
        except (socket.gaierror, UnicodeError) as exc:
            raise UnsafeURLError(f"DNS resolution failed: {exc}") from exc
        literals = [info[4][0] for info in infos]
        if not literals:
            raise UnsafeURLError("host did not resolve to any address") from None

    for ip in literals:
        if not _is_public_ip(ip):
            raise UnsafeURLError(f"host resolves to non-public address: {ip}")
