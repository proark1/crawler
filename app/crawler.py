from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Literal
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import trafilatura
from selectolax.parser import HTMLParser

from .config import settings

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

RenderMode = Literal["auto", "static", "js"]

_pw: "Playwright | None" = None
_browser: "Browser | None" = None
_browser_lock = asyncio.Lock()


async def get_browser() -> "Browser":
    """Lazily start Playwright and launch a single Chromium reused across requests."""
    global _pw, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    async with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        from playwright.async_api import async_playwright

        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(args=["--no-sandbox"])
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


def _extract(html: str, url: str) -> tuple[str | None, str | None, list[str], dict]:
    title: str | None = None
    text: str | None = None
    links: list[str] = []
    metadata: dict = {}

    try:
        tree = HTMLParser(html)
        if tree.css_first("title"):
            title = tree.css_first("title").text(strip=True)
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

    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    if extracted:
        text = extracted

    return title, text, links, metadata


def _looks_empty(text: str | None) -> bool:
    return not text or len(text.strip()) < 200


async def _fetch_static(url: str) -> tuple[int, str, str]:
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,*/*;q=0.8"}
    timeout = httpx.Timeout(settings.request_timeout)
    async with httpx.AsyncClient(
        follow_redirects=True, headers=headers, timeout=timeout
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.status_code, str(resp.url), resp.text


async def _fetch_js(url: str) -> tuple[int, str, str]:
    browser = await get_browser()
    context = await browser.new_context(user_agent=settings.user_agent)
    try:
        page = await context.new_page()
        response = await page.goto(
            url,
            wait_until="networkidle",
            timeout=settings.js_render_timeout * 1000,
        )
        html = await page.content()
        status = response.status if response else 200
        final_url = page.url
        return status, final_url, html
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

    static_html: str | None = None
    static_error: str | None = None

    if render in ("auto", "static"):
        try:
            status, final_url, html = await _fetch_static(url)
            static_html = html
            result["status"] = status
            result["final_url"] = final_url
            title, text, links, metadata = _extract(html, final_url)
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
            title, text, links, metadata = _extract(html, final_url)
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
    return urlparse(a).netloc == urlparse(b).netloc


async def crawl_site(
    start_url: str,
    render: RenderMode = "auto",
    max_depth: int = 1,
    max_pages: int = 10,
    same_host_only: bool = True,
    concurrency: int = 4,
) -> list[CrawlResult]:
    max_depth = min(max_depth, settings.max_depth_hard_limit)
    max_pages = min(max_pages, settings.max_pages_hard_limit)

    start = _normalize(start_url)
    seen: set[str] = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    results: list[CrawlResult] = []
    sem = asyncio.Semaphore(concurrency)

    async def worker(url: str, depth: int) -> tuple[CrawlResult, int]:
        async with sem:
            res = await crawl_one(url, render=render)
            return res, depth

    while queue and len(results) < max_pages:
        batch: list[tuple[str, int]] = []
        while queue and len(batch) < concurrency and len(results) + len(batch) < max_pages:
            batch.append(queue.popleft())

        crawled = await asyncio.gather(
            *(worker(u, d) for u, d in batch), return_exceptions=False
        )

        for res, depth in crawled:
            results.append(res)
            if depth >= max_depth:
                continue
            for link in res.get("links", []):
                if link in seen:
                    continue
                if same_host_only and not _same_host(link, start):
                    continue
                seen.add(link)
                queue.append((link, depth + 1))

    return results
