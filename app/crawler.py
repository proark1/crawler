from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from . import robots
from .config import settings
from .extract import extract, looks_empty
from .fetcher import close_client, safe_get
from .ratelimit import HostThrottle
from .urls import host_of, normalize, same_host

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

RenderMode = Literal["auto", "static", "js"]

_pw: Playwright | None = None
_browser: Browser | None = None
_browser_lock = asyncio.Lock()
_js_sem = asyncio.Semaphore(settings.js_concurrency)
_throttle = HostThrottle(settings.per_host_delay)

# Resource types we never need for text extraction; aborting them speeds up
# JS rendering dramatically and cuts bandwidth.
_BLOCKED_RESOURCES = {"image", "media", "font"}


class CrawlResult(dict):
    """Plain dict result; keeping a class for clarity at call sites."""


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
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",  # avoid /dev/shm exhaustion crashes in Docker
                "--disable-gpu",
            ]
        )
        return _browser


async def close_browser() -> None:
    """Shut down the shared browser and HTTP client. Call on app shutdown."""
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
    await close_client()


def _new_result(url: str) -> CrawlResult:
    return CrawlResult(
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
    )


async def _block_routes(route) -> None:  # type: ignore[no-untyped-def]
    if route.request.resource_type in _BLOCKED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


async def _fetch_js(url: str) -> tuple[int, str, str]:
    browser = await get_browser()
    async with _js_sem:
        context = await browser.new_context(user_agent=settings.user_agent)
        try:
            await context.route("**/*", _block_routes)
            page = await context.new_page()
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=settings.js_render_timeout * 1000
            )
            # Give SPAs a brief chance to settle without hanging on chatty pages.
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=min(5000, settings.js_render_timeout * 1000)
                )
            except Exception:  # noqa: BLE001 - networkidle is best-effort
                pass
            html = await page.content()
            status = response.status if response else 200
            return status, page.url, html
        finally:
            await context.close()


async def crawl_one(
    url: str, render: RenderMode = "auto", *, check_robots: bool = False
) -> CrawlResult:
    url = normalize(url)
    result = _new_result(url)

    if check_robots and not await robots.can_fetch(url):
        result["error"] = "blocked by robots.txt"
        result["metadata"]["robots"] = "disallowed"
        return result

    static_ok = False
    static_error: str | None = None

    if render in ("auto", "static"):
        fetched = await safe_get(url)
        result["status"] = fetched.status
        result["final_url"] = fetched.final_url
        if fetched.error:
            static_error = fetched.error
            result["metadata"]["static_error"] = static_error
        elif fetched.html is not None:
            static_ok = True
            ex = await asyncio.to_thread(extract, fetched.html, fetched.final_url or url)
            result.update(
                title=ex.title, text=ex.text, markdown=ex.markdown,
                links=ex.links, metadata={**result["metadata"], **ex.metadata},
                html=fetched.html,
            )
            if fetched.truncated:
                result["metadata"]["truncated"] = True
        else:
            # Reachable but non-HTML (e.g. a PDF); record and skip parsing.
            result["metadata"].update(fetched.meta)

    needs_js = render == "js" or (
        render == "auto" and (not static_ok or looks_empty(result.get("text")))
    )

    if needs_js:
        try:
            status, final_url, html = await _fetch_js(url)
            result["status"] = status
            result["final_url"] = final_url
            ex = await asyncio.to_thread(extract, html, final_url)
            result.update(
                title=ex.title, text=ex.text, markdown=ex.markdown,
                links=ex.links, metadata={**result["metadata"], **ex.metadata},
                html=html, render_mode="js",
            )
        except Exception as exc:  # noqa: BLE001
            js_error = f"{type(exc).__name__}: {exc}"
            result["metadata"]["js_error"] = js_error
            if not static_ok:
                result["error"] = js_error

    if result["error"] is None and result["status"] is None and not static_ok:
        result["error"] = static_error or "fetch failed"

    return result


async def crawl_site(
    start_url: str,
    render: RenderMode = "auto",
    max_depth: int = 1,
    max_pages: int = 10,
    same_host_only: bool = True,
    concurrency: int | None = None,
    on_page: Callable[[CrawlResult], Awaitable[None]] | None = None,
) -> list[CrawlResult]:
    """Breadth-first crawl using a continuous worker pool.

    ``on_page`` is awaited for each completed page (used to stream progress and
    persist incrementally) as soon as it finishes, rather than at the end.
    """
    max_depth = min(max_depth, settings.max_depth_hard_limit)
    max_pages = min(max_pages, settings.max_pages_hard_limit)
    workers = concurrency or settings.crawl_concurrency

    start = normalize(start_url)
    seen: set[str] = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    results: list[CrawlResult] = []
    lock = asyncio.Lock()
    inflight = 0
    progressed = asyncio.Event()

    async def process(url: str, depth: int) -> None:
        nonlocal inflight
        try:
            if settings.respect_robots and not await robots.can_fetch(url):
                res = _new_result(url)
                res["error"] = "blocked by robots.txt"
                res["metadata"]["robots"] = "disallowed"
            else:
                await _throttle.wait(host_of(url), await robots.crawl_delay(url))
                res = await crawl_one(url, render=render)

            emit = False
            async with lock:
                if len(results) < max_pages:
                    results.append(res)
                    emit = True
                    if depth < max_depth:
                        for link in res.get("links", []):
                            if link in seen:
                                continue
                            if same_host_only and not same_host(link, start):
                                continue
                            seen.add(link)
                            queue.append((link, depth + 1))
            if emit and on_page is not None:
                await on_page(res)
        finally:
            async with lock:
                inflight -= 1
            progressed.set()

    tasks: set[asyncio.Task] = set()
    while True:
        async with lock:
            while queue and len(results) + inflight < max_pages and len(tasks) < workers:
                url, depth = queue.popleft()
                inflight += 1
                tasks.add(asyncio.create_task(process(url, depth)))
            finished = len(results) >= max_pages or (not queue and inflight == 0)
        tasks = {t for t in tasks if not t.done()}
        if finished and not tasks:
            break
        progressed.clear()
        await progressed.wait()

    return results[:max_pages]
