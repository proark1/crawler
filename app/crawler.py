from __future__ import annotations

import asyncio
import time
from collections import defaultdict
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

from .config import settings

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

RenderMode = Literal["auto", "static", "js"]

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
    """Shut down the shared browser. Call on app shutdown."""
    global _pw, _browser
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


class CrawlResult(dict):
    """Plain dict result; keeping a class for clarity at call sites."""


def _normalize(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


def _is_html(content_type: str | None) -> bool:
    if not content_type:
        return True  # be permissive when the server omits the header
    ct = content_type.split(";", 1)[0].strip().lower()
    return ct.startswith("text/") or ct in _HTML_CONTENT_TYPES


def _extract_sync(html: str, url: str) -> tuple[str | None, str | None, list[str], dict]:
    """CPU-bound parsing. Runs in a worker thread via asyncio.to_thread."""
    title: str | None = None
    text: str | None = None
    links: list[str] = []
    metadata: dict = {}

    try:
        tree = HTMLParser(html)
        title_node = tree.css_first("title")
        if title_node:
            title = title_node.text(strip=True)
        seen: set[str] = set()
        for a in tree.css("a[href]"):
            href = a.attributes.get("href")
            if not href:
                continue
            absolute = _normalize(urljoin(url, href))
            if absolute.startswith(("http://", "https://")) and absolute not in seen:
                seen.add(absolute)
                links.append(absolute)
    except Exception as exc:  # noqa: BLE001
        metadata["parse_error"] = str(exc)

    try:
        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if extracted:
            text = extracted
    except Exception as exc:  # noqa: BLE001
        metadata["extract_error"] = str(exc)

    return title, text, links, metadata


async def _extract(html: str, url: str) -> tuple[str | None, str | None, list[str], dict]:
    """Async wrapper that keeps heavy parsing off the event loop."""
    return await asyncio.to_thread(_extract_sync, html, url)


def _looks_empty(text: str | None) -> bool:
    return not text or len(text.strip()) < 200


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
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(min(settings.request_timeout, 10.0)),
                headers={"User-Agent": settings.user_agent},
            ) as client:
                resp = await client.get(f"{origin}/robots.txt")
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


async def _respect_delay(url: str) -> None:
    """Enforce a minimum gap between hits to the same host."""
    delay = settings.per_host_delay
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


async def _fetch_static(url: str) -> tuple[int, str, str | None, str | None]:
    """Return (status, final_url, content_type, text). text is None for non-HTML/oversized."""
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,*/*;q=0.8"}
    timeout = httpx.Timeout(settings.request_timeout)

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(settings.max_retries + 1),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    )
    async def _do() -> tuple[int, str, str | None, str | None]:
        await _respect_delay(url)
        async with httpx.AsyncClient(
            follow_redirects=True, headers=headers, timeout=timeout
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type")
                if not _is_html(content_type):
                    await resp.aclose()
                    return resp.status_code, str(resp.url), content_type, None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > settings.max_response_bytes:
                        await resp.aclose()
                        return resp.status_code, str(resp.url), content_type, None
                    chunks.append(chunk)
                body = b"".join(chunks)
                text = body.decode(resp.encoding or "utf-8", errors="replace")
                return resp.status_code, str(resp.url), content_type, text

    return await _do()


async def _fetch_js(url: str) -> tuple[int, str, str]:
    browser = await get_browser()
    context = await browser.new_context(user_agent=settings.user_agent)
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
        # Give client-side rendering a brief moment to settle, but never block
        # forever waiting for networkidle on pages that never go idle.
        try:
            await page.wait_for_load_state(
                "networkidle", timeout=min(5000, settings.js_render_timeout * 1000)
            )
        except Exception:  # noqa: BLE001 -- networkidle is best-effort
            pass
        html = await page.content()
        return status, page.url, html
    finally:
        await context.close()


async def crawl_one(url: str, render: RenderMode = "auto") -> CrawlResult:
    url = _normalize(url)
    result = CrawlResult(
        url=url,
        final_url=None,
        status=None,
        title=None,
        text=None,
        html=None,
        links=[],
        metadata={},
        render_mode="static",
        error=None,
    )

    if not await _allowed_by_robots(url):
        result["error"] = "blocked by robots.txt"
        result["metadata"]["robots"] = "disallowed"
        return result

    static_html: str | None = None
    static_error: str | None = None

    if render in ("auto", "static"):
        try:
            status, final_url, content_type, html = await _fetch_static(url)
            result["status"] = status
            result["final_url"] = final_url
            if html is None:
                # Non-HTML or oversized: record metadata, nothing to extract.
                result["metadata"]["content_type"] = content_type
                result["metadata"]["skipped"] = "non-html or oversized body"
            else:
                static_html = html
                title, text, links, metadata = await _extract(html, final_url)
                result.update(
                    title=title, text=text, links=links, metadata=metadata, html=html
                )
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
            title, text, links, metadata = await _extract(html, final_url)
            merged_meta = {**result["metadata"], **metadata}
            result.update(
                title=title,
                text=text,
                links=links,
                metadata=merged_meta,
                html=html,
                render_mode="js",
            )
        except Exception as exc:  # noqa: BLE001
            js_error = f"{type(exc).__name__}: {exc}"
            result["metadata"]["js_error"] = js_error
            if static_html is None:
                result["error"] = js_error

    if result["error"] is None and result["status"] is None:
        result["error"] = static_error or "fetch failed"

    return result


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


async def crawl_site(
    start_url: str,
    render: RenderMode = "auto",
    max_depth: int = 1,
    max_pages: int = 10,
    same_host_only: bool = True,
    concurrency: int | None = None,
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

    async def worker() -> None:
        while True:
            url, depth = await queue.get()
            try:
                async with results_lock:
                    over_budget = len(results) >= max_pages
                if over_budget:
                    continue  # budget reached: drain the queue without fetching
                res = await crawl_one(url, render=render)
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
