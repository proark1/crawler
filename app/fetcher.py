"""Shared, SSRF-safe HTTP client for static fetches.

A single pooled httpx client is reused across the process (keep-alive, fewer TLS
handshakes). Redirects are followed manually so every hop can be re-validated
against the SSRF guard, and bodies are streamed with a hard size cap so a single
giant response can't OOM the worker.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from .config import settings
from .urls import UnsafeURLError, assert_safe_url

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()

_HTML_TYPES = ("text/html", "application/xhtml", "application/xml", "text/xml", "+xml")


@dataclass
class FetchResult:
    status: int | None = None
    final_url: str | None = None
    html: str | None = None
    content_type: str | None = None
    error: str | None = None
    truncated: bool = False
    meta: dict = field(default_factory=dict)


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            _client = httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(settings.request_timeout),
                headers={
                    "User-Agent": settings.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _is_htmlish(content_type: str | None) -> bool:
    if not content_type:
        return True  # be lenient when the server omits the header
    ct = content_type.lower()
    return any(t in ct for t in _HTML_TYPES)


async def _read_capped(resp: httpx.Response) -> tuple[str, bool]:
    """Read a streamed response body up to the configured byte cap."""
    cap = settings.max_response_bytes
    chunks: list[bytes] = []
    total = 0
    truncated = False
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > cap:
            chunks.append(chunk[: cap - (total - len(chunk))])
            truncated = True
            break
        chunks.append(chunk)
    body = b"".join(chunks)
    encoding = resp.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace"), truncated
    except (LookupError, TypeError):
        return body.decode("utf-8", errors="replace"), truncated


async def _fetch_once(url: str, *, block_private: bool) -> FetchResult:
    client = await get_client()
    current = url
    for _ in range(settings.max_redirects + 1):
        assert_safe_url(current, block_private=block_private)
        async with client.stream("GET", current) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    return FetchResult(status=resp.status_code, final_url=current,
                                       error="redirect without Location header")
                current = urljoin(current, location)
                await resp.aclose()
                continue

            content_type = resp.headers.get("content-type")
            result = FetchResult(
                status=resp.status_code,
                final_url=str(resp.url),
                content_type=content_type,
            )
            if not _is_htmlish(content_type):
                result.meta["skipped"] = f"non-HTML content-type: {content_type}"
                return result
            html, truncated = await _read_capped(resp)
            result.html = html
            result.truncated = truncated
            return result

    return FetchResult(error=f"too many redirects (>{settings.max_redirects})")


_TRANSIENT = (httpx.TransportError, httpx.TimeoutException)


async def safe_get(url: str, *, block_private: bool | None = None) -> FetchResult:
    """Fetch a URL with SSRF validation, size cap, and bounded retries.

    Never raises for the common failure modes — returns a FetchResult whose
    ``error`` is populated instead, so a single bad page can't abort a crawl.
    """
    if block_private is None:
        block_private = settings.block_private_addresses

    attempts = settings.fetch_retries + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await _fetch_once(url, block_private=block_private)
        except UnsafeURLError as exc:
            return FetchResult(error=f"blocked: {exc}")
        except _TRANSIENT as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (2**attempt))  # 0.5s, 1s, 2s ...
                continue
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the crawl
            return FetchResult(error=f"{type(exc).__name__}: {exc}")
    return FetchResult(error=f"{type(last_exc).__name__}: {last_exc}")
