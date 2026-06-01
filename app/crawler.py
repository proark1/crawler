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

from . import ssrf
from .config import settings

if TYPE_CHECKING:
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
        context = await browser.new_context(user_agent=settings.user_agent)
        if settings.block_resources_in_js:
            await context.route("**/*", _block_heavy_resources)
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
                return await self._make()
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


async def _block_heavy_resources(route) -> None:  # type: ignore[no-untyped-def]
    if route.request.resource_type in ("image", "media", "font"):
        await route.abort()
    else:
        await route.continue_()


async def get_browser() -> Browser:
    """Lazily start Playwright and launch a single Chromium reused across requests."""
    global _pw, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    async with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        from playwright.async_api import async_playwright

        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        return _browser


async def close_browser() -> None:
    """Shut down the shared browser and context pool. Call on app shutdown."""
    global _pw, _browser
    await _context_pool.close()
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

    # JSON-LD: capture a couple of widely useful fields without dragging in the
    # entire (often huge) graph.
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "author" not in meta:
                a = item.get("author")
                if isinstance(a, dict) and a.get("name"):
                    meta["author"] = a["name"]
                elif isinstance(a, str):
                    meta["author"] = a
            if "published_at" not in meta and item.get("datePublished"):
                meta["published_at"] = item["datePublished"]
            if item.get("@type") and "schema_type" not in meta:
                meta["schema_type"] = item["@type"]
        break  # one ld+json block is plenty

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

    return out


async def _extract(html: str, url: str) -> Extraction:
    """Async wrapper that keeps heavy parsing off the event loop."""
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
            async with httpx.AsyncClient(
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


async def _fetch_static(url: str, cached: dict | None = None) -> StaticFetch:
    """Fetch with manual, SSRF-validated redirects and optional conditional headers."""
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,*/*;q=0.8"}
    if cached:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
    timeout = httpx.Timeout(settings.request_timeout)

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(settings.max_retries + 1),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    async def _do() -> StaticFetch:
        async with httpx.AsyncClient(
            follow_redirects=False, headers=headers, timeout=timeout
        ) as client:
            current = url
            for _ in range(settings.max_redirects + 1):
                await ssrf.assert_url_allowed(current)
                await _respect_delay(current)
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            resp.raise_for_status()
                        current = urljoin(current, location)
                        continue

                    etag = resp.headers.get("etag")
                    last_modified = resp.headers.get("last-modified")
                    if resp.status_code == 304:
                        return StaticFetch(
                            304, current, resp.headers.get("content-type"),
                            None, etag, last_modified, not_modified=True,
                        )
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type")
                    if not _is_html(content_type):
                        await resp.aclose()
                        return StaticFetch(
                            resp.status_code, str(resp.url), content_type, None,
                            etag, last_modified,
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > settings.max_response_bytes:
                            await resp.aclose()
                            return StaticFetch(
                                resp.status_code, str(resp.url), content_type, None,
                                etag, last_modified,
                            )
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    text = body.decode(resp.encoding or "utf-8", errors="replace")
                    return StaticFetch(
                        resp.status_code, str(resp.url), content_type, text,
                        etag, last_modified,
                    )
            raise httpx.HTTPError(f"too many redirects (>{settings.max_redirects})")

    return await _do()


async def _fetch_js(url: str) -> tuple[int, str, str]:
    await ssrf.assert_url_allowed(url)
    context = await _context_pool.acquire()
    page = None
    try:
        await _respect_delay(url)
        page = await context.new_page()
        # Let goto failures (DNS, connection, navigation timeout) propagate so the
        # caller records a real error instead of a fake 200.
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=settings.js_render_timeout * 1000,
        )
        status = response.status if response is not None else 200
        final_url = page.url
        # Validate the post-redirect landing URL too (browser may have followed 3xx).
        await ssrf.assert_url_allowed(final_url)
        # Give client-side rendering a brief moment to settle, but never block
        # forever waiting for networkidle on pages that never go idle.
        try:
            await page.wait_for_load_state(
                "networkidle", timeout=min(5000, settings.js_render_timeout * 1000)
            )
        except Exception:  # noqa: BLE001 -- networkidle is best-effort
            pass
        html = await page.content()
        return status, final_url, html
    finally:
        if page is not None:
            await page.close()
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

    static_html: str | None = None
    static_error: str | None = None

    if render in ("auto", "static"):
        try:
            sf = await _fetch_static(url, cached=cached)
            result["status"] = sf.status
            result["final_url"] = sf.final_url
            result["etag"] = sf.etag
            result["last_modified"] = sf.last_modified
            if sf.not_modified:
                # Server says the stored copy is still current; let the caller reuse it.
                result["not_modified"] = True
                return result
            if sf.text is None:
                result["metadata"]["content_type"] = sf.content_type
                result["metadata"]["skipped"] = "non-html or oversized body"
            else:
                static_html = sf.text
                ext = await _extract(sf.text, sf.final_url)
                result["html"] = sf.text
                _apply_extraction(result, ext)
        except Exception as exc:  # noqa: BLE001
            static_error = f"{type(exc).__name__}: {exc}"
            result["metadata"]["static_error"] = static_error

    needs_js = render == "js" or (
        render == "auto" and (static_html is None or _looks_empty(result.get("text")))
    )

    if needs_js:
        try:
            status, final_url, html = await _fetch_js(url)
            result["status"] = status
            result["final_url"] = final_url
            ext = await _extract(html, final_url)
            result["html"] = html
            _apply_extraction(result, ext, render_mode="js")
        except Exception as exc:  # noqa: BLE001
            js_error = f"{type(exc).__name__}: {exc}"
            result["metadata"]["js_error"] = js_error
            if static_html is None:
                result["error"] = js_error

    if result["error"] is None and result["status"] is None:
        result["error"] = static_error or "fetch failed"

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
    if max_age <= 0 or row.get("error"):
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
    return age < max_age


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
) -> list[CrawlResult]:
    max_depth = min(max_depth, settings.max_depth_hard_limit)
    max_pages = min(max_pages, settings.max_pages_hard_limit)
    workers = concurrency or settings.crawl_concurrency

    start = _normalize(start_url)
    seen: set[str] = {start}
    queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
    queue.put_nowait((start, 0))

    results: list[CrawlResult] = []
    results_lock = asyncio.Lock()

    def enqueue_links(res: CrawlResult, depth: int) -> None:
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
                        expand = len(results) < max_pages
                    else:
                        expand = False
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
