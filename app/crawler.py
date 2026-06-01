from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from selectolax.parser import HTMLParser
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from . import antibot, concurrency, httpclient, observability, pdfextract, solver, ssrf, textmeta
from .antibot import Tier
from .config import settings

if TYPE_CHECKING:
    from concurrent.futures import ProcessPoolExecutor

    from playwright.async_api import Browser, BrowserContext, Playwright

RenderMode = Literal["auto", "static", "js"]
CacheLookup = Callable[[str], Awaitable[dict | None]]

_pw: Playwright | None = None
_browser: Browser | None = None
_browser_lock = asyncio.Lock()

# Per-host politeness: serialize the delay window per netloc.
_host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_host_last_hit: dict[str, float] = {}

# Cache of parsed robots.txt per scheme+host so we fetch it at most once.
_robots_cache: dict[str, RobotFileParser | None] = {}
_robots_lock = asyncio.Lock()

# Content types we will attempt to parse as HTML.
_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "application/xml", "text/xml")


# --------------------------------------------------------------------------- #
# Browser lifecycle + context pool                                            #
# --------------------------------------------------------------------------- #


class _ContextPool:
    """Pool of reusable Playwright contexts with resource blocking applied.

    Reusing contexts avoids the per-request cost of spinning up a fresh context,
    and routing lets us drop images/media/fonts so JS rendering is much faster.
    """

    def __init__(self) -> None:
        self._pool: asyncio.Queue[BrowserContext] = asyncio.Queue()
        self._created = 0
        self._lock = asyncio.Lock()
        self._all: list[BrowserContext] = []

    async def _make(self) -> BrowserContext:
        browser = await get_browser()
        context = await browser.new_context(**_context_kwargs())
        if settings.browser_stealth:
            await context.add_init_script(_STEALTH_JS)
        # Validate every request the page makes (not just navigations) so a
        # malicious page can't reach internal hosts via iframes/scripts/XHR,
        # and drop heavy resources for speed.
        await context.route("**/*", _route_request)
        self._all.append(context)
        return context

    async def acquire(self) -> BrowserContext:
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass
        async with self._lock:
            if self._created < max(1, settings.js_context_pool_size):
                self._created += 1
                try:
                    return await self._make()
                except Exception:
                    # Don't leak capacity if context creation failed, or the pool
                    # would permanently shrink and eventually deadlock.
                    self._created -= 1
                    raise
        # Pool is at capacity; wait for one to be released.
        return await self._pool.get()

    async def release(self, context: BrowserContext) -> None:
        await self._pool.put(context)

    async def close(self) -> None:
        for ctx in self._all:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass
        self._all.clear()
        self._created = 0
        self._pool = asyncio.Queue()


_context_pool = _ContextPool()


async def _route_request(route) -> None:  # type: ignore[no-untyped-def]
    # Block any subrequest to a disallowed (private/internal) address.
    try:
        await ssrf.assert_url_allowed(route.request.url)
    except ssrf.BlockedAddressError:
        await route.abort()
        return
    if settings.block_resources_in_js and route.request.resource_type in (
        "image",
        "media",
        "font",
    ):
        await route.abort()
    else:
        await route.continue_()


# JavaScript injected before page scripts run, to hide the most common headless
# tells (navigator.webdriver, missing plugins/languages, absent window.chrome).
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
const _q = window.navigator.permissions && window.navigator.permissions.query;
if (_q) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _q(p);
}
"""


def _playwright_async():  # type: ignore[no-untyped-def]
    """Prefer patchright (a stealth-patched Playwright) when installed and enabled."""
    if settings.browser_stealth:
        try:  # pragma: no cover - depends on optional dep
            from patchright.async_api import async_playwright

            return async_playwright()
        except Exception:  # noqa: BLE001
            pass
    from playwright.async_api import async_playwright

    return async_playwright()


async def get_browser() -> Browser:
    """Lazily start Playwright and launch a single Chromium reused across requests."""
    global _pw, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    async with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        _pw = await _playwright_async().start()
        args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        if settings.browser_stealth:
            args += ["--disable-blink-features=AutomationControlled"]
        _browser = await _pw.chromium.launch(args=args)
        return _browser


def _context_kwargs(proxy: str | None = None) -> dict:
    """Realistic context options (UA, locale, viewport) for stealthy rendering."""
    kwargs: dict = {}
    if settings.antibot_enabled:
        kwargs.update(
            user_agent=antibot._CHROME_UA,
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": settings.accept_language},
        )
    else:
        kwargs["user_agent"] = settings.user_agent
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    return kwargs


async def close_browser() -> None:
    """Shut down the shared browser, context pool, and pooled HTTP clients."""
    global _pw, _browser
    await _context_pool.close()
    await httpclient.aclose_all()
    _shutdown_extract_pool()
    if _browser is not None:
        try:
            await _browser.close()
        finally:
            _browser = None
    if _pw is not None:
        try:
            await _pw.stop()
        finally:
            _pw = None


# --------------------------------------------------------------------------- #
# Result / fetch data types                                                   #
# --------------------------------------------------------------------------- #


class CrawlResult(dict):
    """Plain dict result; keeping a class for clarity at call sites."""


@dataclass
class StaticFetch:
    status: int
    final_url: str
    content_type: str | None
    text: str | None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    headers: dict[str, str] | None = None
    kind: str = "html"  # "html" | "pdf" | "other"


class EngineUnavailable(Exception):
    """Raised by an engine that isn't installed/configured, so escalation skips it."""


# Optional curl_cffi import for the TLS/HTTP2 impersonation engine.
try:  # pragma: no cover - import probe
    from curl_cffi.requests import AsyncSession as _CurlSession

    _CURL_CFFI = True
except Exception:  # noqa: BLE001
    _CurlSession = None  # type: ignore[assignment]
    _CURL_CFFI = False


@dataclass
class Extraction:
    title: str | None = None
    text: str | None = None
    markdown: str | None = None
    links: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _normalize(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


def _is_html(content_type: str | None) -> bool:
    if not content_type:
        return True  # be permissive when the server omits the header
    ct = content_type.split(";", 1)[0].strip().lower()
    return ct.startswith("text/") or ct in _HTML_CONTENT_TYPES


def _is_pdf(content_type: str | None) -> bool:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return ct in ("application/pdf", "application/x-pdf")


def _content_hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------- #
# Extraction                                                                  #
# --------------------------------------------------------------------------- #


def _extract_structured_metadata(tree: HTMLParser, url: str) -> dict:
    """Pull OpenGraph, JSON-LD, canonical URL, language, author, and date."""
    meta: dict = {}

    def first_attr(selector: str, attr: str) -> str | None:
        node = tree.css_first(selector)
        if node:
            val = node.attributes.get(attr)
            if val:
                return val.strip()
        return None

    html_node = tree.css_first("html")
    if html_node and html_node.attributes.get("lang"):
        meta["language"] = html_node.attributes["lang"].strip()

    canonical = first_attr('link[rel="canonical"]', "href")
    if canonical:
        meta["canonical"] = _normalize(urljoin(url, canonical))

    description = first_attr('meta[name="description"]', "content") or first_attr(
        'meta[property="og:description"]', "content"
    )
    if description:
        meta["description"] = description

    og: dict = {}
    for node in tree.css('meta[property^="og:"]'):
        prop = node.attributes.get("property")
        content = node.attributes.get("content")
        if prop and content:
            og[prop[3:]] = content.strip()
    if og:
        meta["opengraph"] = og

    author = first_attr('meta[name="author"]', "content")
    if author:
        meta["author"] = author

    published = first_attr('meta[property="article:published_time"]', "content")
    if published:
        meta["published_at"] = published

    # JSON-LD: capture widely useful Article/Product fields without dragging in
    # the entire (often huge) graph.
    def _types(item: dict) -> list[str]:
        t = item.get("@type")
        return [t] if isinstance(t, str) else (t if isinstance(t, list) else [])

    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        # Flatten schema.org @graph wrappers.
        flat: list = []
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("@graph"), list):
                flat.extend(it["@graph"])
            else:
                flat.append(it)

        for item in flat:
            if not isinstance(item, dict):
                continue
            types = _types(item)
            if types and "schema_type" not in meta:
                meta["schema_type"] = types[0]
            if "author" not in meta:
                a = item.get("author")
                if isinstance(a, dict) and a.get("name"):
                    meta["author"] = a["name"]
                elif isinstance(a, str):
                    meta["author"] = a
            if "published_at" not in meta and item.get("datePublished"):
                meta["published_at"] = item["datePublished"]
            if "description" not in meta and isinstance(item.get("description"), str):
                meta["description"] = item["description"].strip()[:500]

            # Product / Offer enrichment.
            if any(t in ("Product", "Offer", "AggregateOffer") for t in types) or "offers" in item:
                product: dict = meta.get("product", {})
                if isinstance(item.get("name"), str):
                    product.setdefault("name", item["name"])
                brand = item.get("brand")
                if isinstance(brand, dict) and isinstance(brand.get("name"), str):
                    product.setdefault("brand", brand["name"])
                elif isinstance(brand, str):
                    product.setdefault("brand", brand)
                offers = item.get("offers")
                offer = offers[0] if isinstance(offers, list) and offers else offers
                if isinstance(offer, dict):
                    if isinstance(offer.get("price"), (str, int, float)):
                        product.setdefault("price", str(offer["price"]))
                    if isinstance(offer.get("priceCurrency"), str):
                        product.setdefault("currency", offer["priceCurrency"])
                    if isinstance(offer.get("availability"), str):
                        product.setdefault("availability", offer["availability"].rsplit("/", 1)[-1])
                if product:
                    meta["product"] = product
        if len(flat) and meta.get("schema_type"):
            break  # one informative ld+json block is plenty

    return meta


def _extract_sync(html: str, url: str) -> Extraction:
    """CPU-bound parsing. Runs in a worker thread via asyncio.to_thread."""
    out = Extraction()

    try:
        tree = HTMLParser(html)
        title_node = tree.css_first("title")
        if title_node:
            out.title = title_node.text(strip=True)
        seen: set[str] = set()
        for a in tree.css("a[href]"):
            href = a.attributes.get("href")
            if not href:
                continue
            absolute = _normalize(urljoin(url, href))
            if absolute.startswith(("http://", "https://")) and absolute not in seen:
                seen.add(absolute)
                out.links.append(absolute)
        if settings.extract_metadata:
            out.metadata.update(_extract_structured_metadata(tree, url))
    except Exception as exc:  # noqa: BLE001
        out.metadata["parse_error"] = str(exc)

    try:
        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if extracted:
            out.text = extracted
    except Exception as exc:  # noqa: BLE001
        out.metadata["extract_error"] = str(exc)

    if settings.emit_markdown:
        try:
            md = trafilatura.extract(
                html, url=url, include_comments=False, output_format="markdown"
            )
            if md:
                out.markdown = md
        except Exception:  # noqa: BLE001 -- markdown is best-effort
            pass

    # Reading stats (always) and best-effort language detection (when the HTML
    # didn't declare one).
    if out.text:
        words, minutes = textmeta.reading_stats(out.text)
        out.metadata["word_count"] = words
        out.metadata["reading_time_min"] = minutes
        if settings.detect_language and not out.metadata.get("language"):
            lang = textmeta.detect_language(out.text)
            if lang:
                out.metadata["language"] = lang
                out.metadata["language_detected"] = True

    return out


_extract_pool: ProcessPoolExecutor | None = None


def _get_extract_pool():  # type: ignore[no-untyped-def]
    """Lazily create a process pool for true multi-core extraction parallelism."""
    global _extract_pool
    if _extract_pool is None:
        from concurrent.futures import ProcessPoolExecutor

        _extract_pool = ProcessPoolExecutor(max_workers=settings.extract_workers)
    return _extract_pool


def _shutdown_extract_pool() -> None:
    global _extract_pool
    if _extract_pool is not None:
        _extract_pool.shutdown(cancel_futures=True)
        _extract_pool = None


async def _extract(html: str, url: str) -> Extraction:
    """Async wrapper that keeps heavy parsing off the event loop.

    Uses a process pool (true parallelism) when EXTRACT_WORKERS > 0, otherwise a
    thread (GIL-bound, but fine for moderate load and zero spin-up cost).
    """
    if settings.extract_workers > 0:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(_get_extract_pool(), _extract_sync, html, url)
        except Exception:  # noqa: BLE001 -- fall back to threads if the pool dies
            pass
    return await asyncio.to_thread(_extract_sync, html, url)


def _looks_empty(text: str | None) -> bool:
    return not text or len(text.strip()) < 200


# --------------------------------------------------------------------------- #
# robots.txt + politeness                                                     #
# --------------------------------------------------------------------------- #


async def _get_robots(url: str) -> RobotFileParser | None:
    """Fetch and cache robots.txt for the URL's origin. None means 'no rules / allow'."""
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin in _robots_cache:
        return _robots_cache[origin]
    async with _robots_lock:
        if origin in _robots_cache:
            return _robots_cache[origin]
        rp: RobotFileParser | None = RobotFileParser()
        robots_url = f"{origin}/robots.txt"
        try:
            await ssrf.assert_url_allowed(robots_url)
            async with ssrf.build_async_client(
                follow_redirects=True,
                timeout=httpx.Timeout(min(settings.request_timeout, 10.0)),
                headers={"User-Agent": settings.user_agent},
            ) as client:
                resp = await client.get(robots_url)
            if resp.status_code >= 400:
                rp = None  # no robots.txt -> allow everything
            else:
                rp.parse(resp.text.splitlines())
        except Exception:  # noqa: BLE001 -- unreachable robots.txt -> fail open
            rp = None
        _robots_cache[origin] = rp
        return rp


async def _allowed_by_robots(url: str) -> bool:
    if not settings.respect_robots:
        return True
    rp = await _get_robots(url)
    if rp is None:
        return True
    return rp.can_fetch(settings.user_agent, url)


def _parse_sitemap(xml: str) -> tuple[list[str], bool]:
    """Return (<loc> URLs, is_sitemap_index). Namespace-agnostic and defensive."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], False
    is_index = root.tag.rsplit("}", 1)[-1].lower() == "sitemapindex"
    locs = [
        el.text.strip()
        for el in root.iter()
        if el.tag.rsplit("}", 1)[-1].lower() == "loc" and el.text and el.text.strip()
    ]
    return locs, is_index


async def _fetch_sitemap_text(url: str) -> str | None:
    # Follow redirects manually, validating each hop, so a sitemap URL can't
    # redirect us into an internal service (SSRF).
    client = httpclient.get_client(None)
    current = url
    resp = None
    for _ in range(settings.max_redirects + 1):
        await ssrf.assert_url_allowed(current)
        resp = await client.get(
            current, headers=antibot.browser_headers(current), follow_redirects=False
        )
        if 300 <= resp.status_code < 400:
            location = resp.headers.get("location")
            if not location:
                return None
            current = urljoin(current, location)
            continue
        break
    else:
        return None

    if resp.status_code >= 400:
        return None
    content = resp.content
    if len(content) > settings.max_response_bytes:
        return None
    # Detect gzip by magic bytes (robust against missing extension / wrong type).
    if content.startswith(b"\x1f\x8b"):
        import gzip

        try:
            content = gzip.decompress(content)
        except Exception:  # noqa: BLE001
            return None
    return content.decode("utf-8", errors="replace")


async def discover_sitemap_urls(start_url: str, limit: int | None = None) -> list[str]:
    """Collect page URLs from a site's sitemaps (robots `Sitemap:` lines, else
    /sitemap.xml), following sitemap-index files. Best-effort and bounded."""
    from collections import deque

    limit = limit or settings.sitemap_max_urls
    parts = urlparse(start_url)
    origin = f"{parts.scheme}://{parts.netloc}"

    sitemaps: list[str] = []
    rp = await _get_robots(start_url)
    if rp is not None:
        try:
            sitemaps = list(rp.site_maps() or [])
        except Exception:  # noqa: BLE001
            sitemaps = []
    if not sitemaps:
        sitemaps = [f"{origin}/sitemap.xml"]

    found: list[str] = []
    seen_maps: set[str] = set()
    queue: deque[str] = deque(sitemaps)
    while queue and len(found) < limit and len(seen_maps) < 50:
        sm = queue.popleft()
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            xml = await _fetch_sitemap_text(sm)
        except Exception:  # noqa: BLE001 -- sitemaps are best-effort
            continue
        if not xml:
            continue
        locs, is_index = _parse_sitemap(xml)
        if is_index:
            for loc in locs:
                if loc not in seen_maps:
                    queue.append(loc)
        else:
            for loc in locs:
                found.append(loc)
                if len(found) >= limit:
                    break
    return found[:limit]


async def _effective_delay(url: str) -> float:
    delay = settings.per_host_delay
    if settings.respect_crawl_delay:
        rp = await _get_robots(url)
        if rp is not None:
            try:
                cd = rp.crawl_delay(settings.user_agent)
            except Exception:  # noqa: BLE001
                cd = None
            if cd:
                delay = max(delay, float(cd))
    return delay


async def _respect_delay(url: str) -> None:
    """Enforce a minimum gap between hits to the same host (robots crawl-delay aware)."""
    delay = await _effective_delay(url)
    if delay <= 0:
        return
    host = urlparse(url).netloc
    async with _host_locks[host]:
        last = _host_last_hit.get(host)
        now = time.monotonic()
        if last is not None:
            wait = delay - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
        _host_last_hit[host] = time.monotonic()


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


# --------------------------------------------------------------------------- #
# Fetching                                                                    #
# --------------------------------------------------------------------------- #


def _conditional_headers(headers: dict[str, str], cached: dict | None) -> dict[str, str]:
    if cached:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
    return headers


def _is_block(status: int | None, headers: dict[str, str], html: str | None) -> bool:
    """True if anti-bot is on and this response looks like a block/challenge."""
    return settings.antibot_enabled and antibot.detect_block(status, headers, html).blocked


def _kept_headers(resp_headers) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Keep just the response headers block detection / caching care about."""
    keep = (
        "server", "cf-mitigated", "content-type", "set-cookie", "x-powered-by",
        "cache-control", "age",
    )
    out: dict[str, str] = {}
    for k in keep:
        v = resp_headers.get(k)
        if v:
            out[k] = v
    return out


def _cache_max_age(headers: dict[str, str] | None) -> int | None:
    """Effective freshness lifetime (seconds) from Cache-Control/Age, or None.

    Returns 0 for no-store/no-cache so such pages are never treated as fresh.
    """
    if not headers:
        return None
    cc = (headers.get("cache-control") or "").lower()
    if not cc:
        return None
    if "no-store" in cc or "no-cache" in cc:
        return 0
    max_age = None
    for part in cc.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                return None
            break
    if max_age is None:
        return None
    try:
        age = int(headers.get("age", "0") or 0)
    except ValueError:
        age = 0
    return max(0, max_age - age)


async def _fetch_static(url: str, cached: dict | None = None) -> StaticFetch:
    """Tier 0: pooled httpx fetch with browser headers and SSRF-validated redirects.

    Does not raise for 4xx / 503 — those bodies are returned so the block
    detector can classify a challenge; genuine 5xx still raise to trigger retry.
    """
    headers = _conditional_headers(antibot.browser_headers(url), cached)
    host = urlparse(url).hostname or ""
    proxy = antibot.proxies.pick(host, int(Tier.STATIC))
    client = httpclient.get_client(proxy)
    timeout = httpx.Timeout(settings.request_timeout)

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(settings.max_retries + 1),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    async def _do() -> StaticFetch:
        current = url
        for _ in range(settings.max_redirects + 1):
            await ssrf.assert_url_allowed(current)
            await _respect_delay(current)
            async with client.stream("GET", current, headers=headers, timeout=timeout) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise httpx.HTTPError("redirect response missing Location header")
                    current = urljoin(current, location)
                    continue

                etag = resp.headers.get("etag")
                last_modified = resp.headers.get("last-modified")
                kept = _kept_headers(resp.headers)
                if resp.status_code == 304:
                    return StaticFetch(
                        304, current, resp.headers.get("content-type"),
                        None, etag, last_modified, not_modified=True, headers=kept,
                    )
                content_type = resp.headers.get("content-type")
                is_5xx = 500 <= resp.status_code < 600
                is_pdf = _is_pdf(content_type)
                if not _is_html(content_type) and not (is_pdf and settings.extract_pdf):
                    await resp.aclose()
                    # A non-HTML 5xx that isn't a recognised block is a genuine
                    # server error -> raise so tenacity retries it.
                    if is_5xx and not _is_block(resp.status_code, kept, None):
                        resp.raise_for_status()
                    return StaticFetch(
                        resp.status_code, str(resp.url), content_type, None,
                        etag, last_modified, headers=kept, kind="other",
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > settings.max_response_bytes:
                        await resp.aclose()
                        return StaticFetch(
                            resp.status_code, str(resp.url), content_type, None,
                            etag, last_modified, headers=kept,
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
                if is_pdf:
                    pdf_text = await asyncio.to_thread(pdfextract.extract_text, body)
                    return StaticFetch(
                        resp.status_code, str(resp.url), content_type, pdf_text,
                        etag, last_modified, headers=kept, kind="pdf",
                    )
                text = body.decode(resp.encoding or "utf-8", errors="replace")
                # Genuine 5xx (not a bot-protection challenge) -> retry; a 5xx
                # challenge body is returned so escalation can handle it.
                if is_5xx and not _is_block(resp.status_code, kept, text):
                    resp.raise_for_status()
                return StaticFetch(
                    resp.status_code, str(resp.url), content_type, text,
                    etag, last_modified, headers=kept,
                )
        raise httpx.HTTPError(f"too many redirects (>{settings.max_redirects})")

    return await _do()


async def _fetch_impersonate(url: str, cached: dict | None = None) -> StaticFetch:
    """Tier 1: curl_cffi fetch impersonating a real browser's TLS/HTTP2 fingerprint.

    Beats passive Cloudflare/Akamai fingerprint checks that plain httpx fails.
    Raises EngineUnavailable when curl_cffi isn't installed.
    """
    if not (_CURL_CFFI and settings.impersonate_browser):
        raise EngineUnavailable("curl_cffi not installed or impersonation disabled")

    host = urlparse(url).hostname or ""
    proxy = antibot.proxies.pick(host, int(Tier.IMPERSONATE))
    # Let curl_cffi's impersonation own the fingerprint-sensitive headers
    # (UA/sec-ch-ua/Accept); only add Accept-Language and conditional headers.
    headers = _conditional_headers({"Accept-Language": settings.accept_language}, cached)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    # Follow redirects manually, validating every hop *before* the request, so
    # a public URL can't redirect us into an internal service (SSRF). curl_cffi
    # does its own DNS, so a small rebinding window remains (documented in
    # SECURITY.md for this tier).
    async with _CurlSession() as session:
        current = url
        resp = None
        for _ in range(settings.max_redirects + 1):
            await ssrf.assert_url_allowed(current)
            await _respect_delay(current)
            resp = await session.get(
                current,
                headers=headers,
                impersonate=settings.impersonate_browser,
                proxies=proxies,
                allow_redirects=False,
                timeout=settings.request_timeout,
            )
            if 300 <= resp.status_code < 400:
                location = resp.headers.get("location")
                if not location:
                    raise httpx.HTTPError("redirect response missing Location header")
                current = urljoin(current, location)
                continue
            break
        else:
            raise httpx.HTTPError(f"too many redirects (>{settings.max_redirects})")
    final_url = str(resp.url)

    resp_headers = {k.lower(): v for k, v in dict(resp.headers).items()}
    kept = _kept_headers(resp_headers)
    etag = resp_headers.get("etag")
    last_modified = resp_headers.get("last-modified")
    if resp.status_code == 304:
        return StaticFetch(304, final_url, resp_headers.get("content-type"), None,
                           etag, last_modified, not_modified=True, headers=kept)
    content_type = resp_headers.get("content-type")
    content = resp.content or b""
    if len(content) > settings.max_response_bytes:
        return StaticFetch(resp.status_code, final_url, content_type, None,
                           etag, last_modified, headers=kept, kind="other")
    if _is_pdf(content_type) and settings.extract_pdf:
        pdf_text = await asyncio.to_thread(pdfextract.extract_text, content)
        return StaticFetch(resp.status_code, final_url, content_type, pdf_text,
                           etag, last_modified, headers=kept, kind="pdf")
    if not _is_html(content_type):
        return StaticFetch(resp.status_code, final_url, content_type, None,
                           etag, last_modified, headers=kept, kind="other")
    text = content.decode(resp.encoding or "utf-8", errors="replace")
    return StaticFetch(resp.status_code, final_url, content_type, text,
                       etag, last_modified, headers=kept)


# Per-host cookie jars (bounded), so a domain that "challenges once, then allows"
# keeps its clearance cookie across renders.
_cookie_jars: dict[str, list] = {}


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


async def _fetch_js(url: str) -> tuple[int, str, str]:
    await ssrf.assert_url_allowed(url)
    host = _host_of(url)
    proxy = antibot.proxies.pick(host, int(Tier.BROWSER))

    # A proxied render needs its own context (the pool's contexts are direct);
    # otherwise reuse a pooled context for speed.
    dedicated = proxy is not None
    if dedicated:
        browser = await get_browser()
        context = await browser.new_context(**_context_kwargs(proxy))
        if settings.browser_stealth:
            await context.add_init_script(_STEALTH_JS)
        await context.route("**/*", _route_request)
    else:
        context = await _context_pool.acquire()

    page = None
    try:
        await _respect_delay(url)
        if settings.persist_cookies and _cookie_jars.get(host):
            try:
                await context.add_cookies(_cookie_jars[host])
            except Exception:  # noqa: BLE001
                pass
        page = await context.new_page()
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=settings.js_render_timeout * 1000,
        )
        status = response.status if response is not None else 200
        final_url = page.url
        await ssrf.assert_url_allowed(final_url)
        try:
            await page.wait_for_load_state(
                "networkidle", timeout=min(5000, settings.js_render_timeout * 1000)
            )
        except Exception:  # noqa: BLE001 -- networkidle is best-effort
            pass
        html = await page.content()
        if settings.persist_cookies:
            try:
                jar = await context.cookies()
                if jar:
                    _cookie_jars[host] = jar
                    if len(_cookie_jars) > 5000:
                        _cookie_jars.pop(next(iter(_cookie_jars)))
            except Exception:  # noqa: BLE001
                pass
        return status, final_url, html
    finally:
        if page is not None:
            await page.close()
        if dedicated:
            await context.close()
        else:
            await _context_pool.release(context)


# --------------------------------------------------------------------------- #
# Single page                                                                 #
# --------------------------------------------------------------------------- #


def _apply_extraction(result: CrawlResult, ext: Extraction, *, render_mode: str | None = None) -> None:
    merged_meta = {**result["metadata"], **ext.metadata}
    result.update(
        title=ext.title,
        text=ext.text,
        markdown=ext.markdown,
        links=ext.links,
        metadata=merged_meta,
    )
    result["content_hash"] = _content_hash(ext.text)
    if render_mode:
        result["render_mode"] = render_mode


async def crawl_one(
    url: str, render: RenderMode = "auto", cached: dict | None = None
) -> CrawlResult:
    url = _normalize(url)
    result = CrawlResult(
        url=url,
        final_url=None,
        status=None,
        title=None,
        text=None,
        markdown=None,
        html=None,
        links=[],
        metadata={},
        render_mode="static",
        error=None,
        etag=None,
        last_modified=None,
        content_hash=None,
        not_modified=False,
        from_cache=False,
    )

    try:
        await ssrf.assert_url_allowed(url)
    except ssrf.BlockedAddressError as exc:
        result["error"] = f"blocked: {exc}"
        result["metadata"]["ssrf"] = str(exc)
        return result

    if not await _allowed_by_robots(url):
        result["error"] = "blocked by robots.txt"
        result["metadata"]["robots"] = "disallowed"
        return result

    return await _crawl_escalating(url, render, cached, result)


def _tier_plan(url: str, render: RenderMode) -> list[int]:
    """Ordered engine tiers to try for this request."""
    if render == "static":
        return [int(Tier.STATIC)]
    if render == "js":
        return [int(Tier.BROWSER)]
    # auto: start from what worked for this domain last time, escalate upward.
    start = antibot.profiles.suggested_tier(url) if settings.antibot_enabled else int(Tier.STATIC)
    candidates = [int(Tier.STATIC), int(Tier.IMPERSONATE), int(Tier.BROWSER)]
    if settings.flaresolverr_url:  # only attempt the solver tier when configured
        candidates.append(int(Tier.SOLVER))
    tiers = [t for t in candidates if t >= start]
    return tiers or [int(Tier.BROWSER)]


async def _run_engine(tier: int, url: str, cached: dict | None):
    """Invoke one engine; returns (status, final_url, content_type, html, etag,
    last_modified, not_modified, headers, kind). Raises EngineUnavailable to skip."""
    if tier == int(Tier.STATIC):
        sf = await _fetch_static(url, cached=cached)
        return (sf.status, sf.final_url, sf.content_type, sf.text, sf.etag,
                sf.last_modified, sf.not_modified, sf.headers or {}, sf.kind)
    if tier == int(Tier.IMPERSONATE):
        sf = await _fetch_impersonate(url, cached=cached)
        return (sf.status, sf.final_url, sf.content_type, sf.text, sf.etag,
                sf.last_modified, sf.not_modified, sf.headers or {}, sf.kind)
    if tier == int(Tier.SOLVER):
        host = _host_of(url)
        await ssrf.assert_url_allowed(url)
        try:
            res = await solver.solve(url, proxy=antibot.proxies.pick(host, int(Tier.SOLVER)))
        except solver.SolverUnavailable as exc:
            raise EngineUnavailable(str(exc)) from exc
        await ssrf.assert_url_allowed(res.url)
        if settings.persist_cookies and res.cookies:
            _cookie_jars[host] = res.cookies  # reuse clearance cookies in later renders
        return (res.status, res.url, None, res.html, None, None, False, {}, "html")
    # BROWSER
    status, final_url, html = await _fetch_js(url)
    return (status, final_url, None, html, None, None, False, {}, "html")


async def _crawl_escalating(
    url: str, render: RenderMode, cached: dict | None, result: CrawlResult
) -> CrawlResult:
    tiers = _tier_plan(url, render)
    last_error: str | None = None
    host = _host_of(url)

    # Stop hammering a host that keeps blocking us until its breaker cools down.
    try:
        concurrency.limiter.check_circuit(host)
    except concurrency.CircuitOpen:
        result["error"] = "circuit open: host temporarily skipped after repeated blocks"
        result["metadata"]["circuit"] = "open"
        return result

    for i, tier in enumerate(tiers):
        is_last = i == len(tiers) - 1
        try:
            async with concurrency.limiter.slot(host):
                (status, final_url, content_type, html, etag,
                 last_modified, not_modified, headers, kind) = await _run_engine(tier, url, cached)
        except concurrency.CircuitOpen:
            result["error"] = "circuit open: host temporarily skipped after repeated blocks"
            result["metadata"]["circuit"] = "open"
            return result
        except EngineUnavailable:
            continue  # engine not installed/configured -> try the next tier
        except ssrf.BlockedAddressError as exc:
            # A redirect hit an internal address. Abort outright — never escalate
            # to another engine, which would re-attempt the blocked target.
            result["error"] = f"blocked: {exc}"
            result["metadata"]["ssrf"] = str(exc)
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            result["metadata"][f"tier{tier}_error"] = last_error
            continue

        result["status"] = status
        result["final_url"] = final_url
        result["etag"] = etag
        result["last_modified"] = last_modified

        if not_modified:
            result["not_modified"] = True
            return result

        # Detect bot-protection blocks before paying for extraction.
        if settings.antibot_enabled:
            signal = antibot.detect_block(status, headers, html)
            if signal.blocked:
                result["metadata"]["block"] = {"vendor": signal.vendor, "reason": signal.reason}
                antibot.profiles.record_block(url, tier, signal.vendor)
                concurrency.limiter.record_block(host)  # back off / trip breaker
                observability.record_block(signal.vendor, tier)
                last_error = f"blocked by {signal.vendor}"
                if settings.escalate_on_block and not is_last:
                    if signal.vendor:  # rotate proxy on a hard block
                        antibot.proxies.rotate(host)
                    continue
                result["error"] = last_error
                return result

        # Record the server's freshness directive (Cache-Control/Age) so future
        # conditional re-crawls can honor it per page.
        if settings.honor_cache_headers:
            cm = _cache_max_age(headers)
            if cm is not None:
                result["metadata"]["cache_max_age"] = cm

        # PDF: `html` holds the extracted plain text; store it directly without
        # running the HTML extractor over it.
        if kind == "pdf":
            if html:
                result["text"] = html
                result["markdown"] = html
                result["content_hash"] = _content_hash(html)
                result["metadata"]["content_type"] = content_type
                words, minutes = textmeta.reading_stats(html)
                result["metadata"]["word_count"] = words
                result["metadata"]["reading_time_min"] = minutes
                if settings.detect_language:
                    lang = textmeta.detect_language(html)
                    if lang:
                        result["metadata"]["language"] = lang
                        result["metadata"]["language_detected"] = True
                result["render_mode"] = "pdf"
                if settings.antibot_enabled:
                    antibot.profiles.record_success(url, tier)
                concurrency.limiter.record_success(host)
                return result
            # Extraction unavailable/failed -> treat as a skipped non-HTML body.
            # The HTTP request still succeeded, so record success like other skips.
            result["metadata"]["content_type"] = content_type
            result["metadata"]["skipped"] = "pdf (no text extracted)"
            result["render_mode"] = "pdf"
            if settings.antibot_enabled:
                antibot.profiles.record_success(url, tier)
            concurrency.limiter.record_success(host)
            return result

        render_mode = "js" if tier == int(Tier.BROWSER) else "static"

        if html is None:  # non-HTML or oversized
            result["metadata"]["content_type"] = content_type
            result["metadata"]["skipped"] = "non-html or oversized body"
            result["render_mode"] = render_mode
            if settings.antibot_enabled:
                antibot.profiles.record_success(url, tier)
            concurrency.limiter.record_success(host)
            return result

        ext = await _extract(html, final_url)
        result["html"] = html
        _apply_extraction(result, ext, render_mode=render_mode)

        # If the page looks client-rendered (empty), escalate to a stronger engine.
        if _looks_empty(result.get("text")) and not is_last:
            continue

        if settings.antibot_enabled:
            antibot.profiles.record_success(url, tier)
        concurrency.limiter.record_success(host)
        return result

    if result["error"] is None and result["status"] is None:
        result["error"] = last_error or "fetch failed"
    return result


# --------------------------------------------------------------------------- #
# Site crawl                                                                  #
# --------------------------------------------------------------------------- #


def _same_host(a: str, b: str) -> bool:
    return _host_key(a) == _host_key(b)


def _host_key(url: str) -> str:
    """Host comparison that treats apex and www. as equal and ignores case."""
    host = urlparse(url).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_fresh(row: dict, max_age: float) -> bool:
    if row.get("error"):
        return False
    # Honor the server's own Cache-Control max-age (per page) in addition to the
    # configured global TTL; the larger of the two wins.
    effective = max_age
    if settings.honor_cache_headers:
        cm = (row.get("metadata") or {}).get("cache_max_age")
        if isinstance(cm, (int, float)) and cm > effective:
            effective = cm
    if effective <= 0:
        return False
    fetched = row.get("fetched_at")
    if not fetched:
        return False
    try:
        dt = datetime.fromisoformat(str(fetched))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - dt).total_seconds()
    return age < effective


def _row_to_result(row: dict) -> CrawlResult:
    res = CrawlResult(row)
    res["from_cache"] = True
    return res


# Public alias for callers outside this module (e.g. the API layer).
is_fresh = _is_fresh


async def crawl_site(
    start_url: str,
    render: RenderMode = "auto",
    max_depth: int = 1,
    max_pages: int = 10,
    same_host_only: bool = True,
    concurrency: int | None = None,
    cache_lookup: CacheLookup | None = None,
    on_page_crawled: Callable[[CrawlResult], None] | None = None,
    use_sitemap: bool = False,
) -> list[CrawlResult]:
    max_depth = min(max_depth, settings.max_depth_hard_limit)
    max_pages = min(max_pages, settings.max_pages_hard_limit)
    workers = concurrency or settings.crawl_concurrency

    start = _normalize(start_url)
    seen: set[str] = {start}
    queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
    queue.put_nowait((start, 0))

    # Seed from the site's sitemap(s) so discovery isn't limited to in-page links.
    # Only when multi-page crawling is enabled (max_depth == 0 = start URL only).
    if use_sitemap and settings.use_sitemap and max_depth > 0:
        try:
            for loc in await discover_sitemap_urls(start):
                norm = _normalize(loc)
                if norm in seen:
                    continue
                if same_host_only and not _same_host(norm, start):
                    continue
                seen.add(norm)
                queue.put_nowait((norm, 1))
        except Exception:  # noqa: BLE001 -- sitemap discovery is best-effort
            pass

    results: list[CrawlResult] = []
    results_lock = asyncio.Lock()
    seen_hashes: set[str] = set()

    def enqueue_links(res: CrawlResult, depth: int) -> None:
        # Treat a page's canonical URL as already seen, so we don't separately
        # crawl duplicate URLs that all point at the same canonical.
        canon = (res.get("metadata") or {}).get("canonical")
        if canon:
            seen.add(canon)
        if depth >= max_depth:
            return
        for link in res.get("links", []):
            if link in seen:
                continue
            if same_host_only and not _same_host(link, start):
                continue
            seen.add(link)
            queue.put_nowait((link, depth + 1))

    async def fetch_with_cache(url: str) -> CrawlResult:
        row = await cache_lookup(url) if cache_lookup else None
        if row and _is_fresh(row, settings.recrawl_max_age):
            return _row_to_result(row)
        cached = (
            {"etag": row.get("etag"), "last_modified": row.get("last_modified")}
            if row
            else None
        )
        if cached is None:
            res = await crawl_one(url, render=render)
        else:
            res = await crawl_one(url, render=render, cached=cached)
        if res.get("not_modified") and row:
            return _row_to_result(row)
        return res

    async def worker() -> None:
        while True:
            url, depth = await queue.get()
            try:
                async with results_lock:
                    over_budget = len(results) >= max_pages
                if over_budget:
                    continue  # budget reached: drain the queue without fetching
                res = await fetch_with_cache(url)
                async with results_lock:
                    if len(results) < max_pages:
                        results.append(res)
                        appended = True
                        expand = len(results) < max_pages
                        # Content-hash dedup: if another URL this run produced the
                        # same content, record it but don't re-expand its (already
                        # crawled) link graph.
                        chash = res.get("content_hash")
                        if settings.dedup_by_content and chash:
                            if chash in seen_hashes:
                                res.setdefault("metadata", {})["duplicate"] = True
                                expand = False
                            else:
                                seen_hashes.add(chash)
                    else:
                        appended = False
                        expand = False
                if appended and on_page_crawled is not None:
                    on_page_crawled(res)  # live progress callback
                if expand:
                    enqueue_links(res, depth)
            finally:
                queue.task_done()

    tasks = [asyncio.create_task(worker()) for _ in range(max(1, workers))]
    try:
        # queue.join() unblocks exactly when every enqueued URL has been processed,
        # which is race-free regardless of how links fan out across workers.
        await queue.join()
    finally:
        # Guarantee workers are torn down even if we're cancelled mid-crawl.
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    return results[:max_pages]
