from __future__ import annotations

import pytest

from app import crawler


def test_normalize_strips_fragment_and_trailing_slash():
    assert crawler._normalize("https://ex.com/a/#frag") == "https://ex.com/a"
    assert crawler._normalize("https://ex.com/") == "https://ex.com"


def test_is_html_detection():
    assert crawler._is_html("text/html; charset=utf-8")
    assert crawler._is_html("application/xhtml+xml")
    assert crawler._is_html(None)  # permissive when missing
    assert not crawler._is_html("application/pdf")
    assert not crawler._is_html("image/png")


def test_host_key_treats_www_and_apex_equal():
    assert crawler._host_key("https://www.ex.com/a") == crawler._host_key("https://ex.com/b")
    assert crawler._same_host("https://EX.com", "https://ex.com/x")
    assert not crawler._same_host("https://a.com", "https://b.com")


def test_looks_empty():
    assert crawler._looks_empty(None)
    assert crawler._looks_empty("   ")
    assert crawler._looks_empty("short")
    assert not crawler._looks_empty("x" * 500)


def test_extract_sync_pulls_title_and_links():
    html = """
    <html><head><title>Hello</title></head>
    <body><a href="/a">A</a><a href="https://other.com/b">B</a>
    <p>%s</p></body></html>
    """ % ("lorem ipsum " * 60)
    title, text, links, meta = crawler._extract_sync(html, "https://ex.com/")
    assert title == "Hello"
    assert "https://ex.com/a" in links
    assert "https://other.com/b" in links
    assert text and "lorem ipsum" in text
    assert "parse_error" not in meta


@pytest.mark.asyncio
async def test_is_transient_classification():
    import httpx

    assert crawler._is_transient(httpx.ConnectTimeout("x"))
    assert crawler._is_transient(httpx.ConnectError("x"))
    resp500 = httpx.Response(503, request=httpx.Request("GET", "https://ex.com"))
    assert crawler._is_transient(httpx.HTTPStatusError("x", request=resp500.request, response=resp500))
    resp404 = httpx.Response(404, request=httpx.Request("GET", "https://ex.com"))
    assert not crawler._is_transient(httpx.HTTPStatusError("x", request=resp404.request, response=resp404))


@pytest.mark.asyncio
async def test_crawl_one_static_path(monkeypatch):
    html = "<html><head><title>T</title></head><body><p>%s</p></body></html>" % ("word " * 80)

    async def fake_static(url):
        return 200, url, "text/html", html

    async def fake_allowed(url):
        return True

    monkeypatch.setattr(crawler, "_fetch_static", fake_static)
    monkeypatch.setattr(crawler, "_allowed_by_robots", fake_allowed)

    res = await crawler.crawl_one("https://ex.com/", render="static")
    assert res["status"] == 200
    assert res["title"] == "T"
    assert res["render_mode"] == "static"
    assert res["error"] is None


@pytest.mark.asyncio
async def test_crawl_one_respects_robots(monkeypatch):
    async def deny(url):
        return False

    monkeypatch.setattr(crawler, "_allowed_by_robots", deny)
    res = await crawler.crawl_one("https://ex.com/secret", render="static")
    assert res["error"] == "blocked by robots.txt"
    assert res["status"] is None


@pytest.mark.asyncio
async def test_crawl_one_auto_falls_back_to_js_when_empty(monkeypatch):
    calls = {"js": 0}

    async def fake_static(url):
        return 200, url, "text/html", "<html><body></body></html>"

    async def fake_js(url):
        calls["js"] += 1
        big = "content " * 100
        return 200, url, f"<html><head><title>JS</title></head><body><p>{big}</p></body></html>"

    async def allowed(url):
        return True

    monkeypatch.setattr(crawler, "_fetch_static", fake_static)
    monkeypatch.setattr(crawler, "_fetch_js", fake_js)
    monkeypatch.setattr(crawler, "_allowed_by_robots", allowed)

    res = await crawler.crawl_one("https://ex.com/", render="auto")
    assert calls["js"] == 1
    assert res["render_mode"] == "js"
    assert res["title"] == "JS"


@pytest.mark.asyncio
async def test_crawl_one_skips_non_html(monkeypatch):
    async def fake_static(url):
        return 200, url, "application/pdf", None

    async def allowed(url):
        return True

    monkeypatch.setattr(crawler, "_fetch_static", fake_static)
    monkeypatch.setattr(crawler, "_allowed_by_robots", allowed)

    res = await crawler.crawl_one("https://ex.com/doc.pdf", render="static")
    assert res["status"] == 200
    assert res["text"] is None
    assert res["metadata"].get("skipped")


@pytest.mark.asyncio
async def test_crawl_site_bfs_respects_max_pages_and_depth(monkeypatch):
    # Build a synthetic link graph: every page links to two same-host children.
    async def fake_crawl_one(url, render="auto"):
        n = url.rstrip("/").split("/")[-1]
        try:
            idx = int(n)
        except ValueError:
            idx = 0
        return crawler.CrawlResult(
            url=url,
            links=[f"https://ex.com/{idx * 2 + 1}", f"https://ex.com/{idx * 2 + 2}",
                   "https://other.com/x"],
            render_mode="static",
            error=None,
        )

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)

    results = await crawler.crawl_site(
        "https://ex.com/0", max_depth=5, max_pages=5, same_host_only=True, concurrency=3
    )
    assert len(results) == 5
    # same_host_only must have excluded other.com
    assert all("other.com" not in r["url"] for r in results)


@pytest.mark.asyncio
async def test_crawl_site_depth_limit(monkeypatch):
    async def fake_crawl_one(url, render="auto"):
        return crawler.CrawlResult(
            url=url,
            links=["https://ex.com/child"],
            render_mode="static",
            error=None,
        )

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)
    # depth 0 => only the start URL is crawled, children not followed
    results = await crawler.crawl_site(
        "https://ex.com/root", max_depth=0, max_pages=50, concurrency=2
    )
    assert len(results) == 1
    assert results[0]["url"] == "https://ex.com/root"
