from __future__ import annotations

from datetime import UTC

import pytest

from app import crawler
from app.config import settings


@pytest.fixture(autouse=True)
def _disable_ssrf(monkeypatch):
    # Unit tests use example hostnames; skip real DNS-based SSRF checks.
    monkeypatch.setattr(settings, "block_private_addresses", False)


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
    ext = crawler._extract_sync(html, "https://ex.com/")
    assert ext.title == "Hello"
    assert "https://ex.com/a" in ext.links
    assert "https://other.com/b" in ext.links
    assert ext.text and "lorem ipsum" in ext.text
    assert "parse_error" not in ext.metadata


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

    async def fake_static(url, cached=None):
        return crawler.StaticFetch(200, url, "text/html", html)

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

    async def fake_static(url, cached=None):
        return crawler.StaticFetch(200, url, "text/html", "<html><body></body></html>")

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
async def test_tier_plan_by_render_mode():
    assert crawler._tier_plan("https://x.com", "static") == [0]
    assert crawler._tier_plan("https://x.com", "js") == [2]
    assert crawler._tier_plan("https://x.com", "auto")[0] == 0  # starts at static


@pytest.mark.asyncio
async def test_tier_plan_includes_solver_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "flaresolverr_url", "")
    assert 3 not in crawler._tier_plan("https://nosolver.com", "auto")
    monkeypatch.setattr(settings, "flaresolverr_url", "http://flaresolverr:8191")
    assert crawler._tier_plan("https://withsolver.com", "auto")[-1] == 3  # SOLVER last


@pytest.mark.asyncio
async def test_crawl_one_escalates_past_cloudflare(monkeypatch):
    cf = "<html><head><title>Just a moment...</title></head><body>cf-chl</body></html>"

    async def fake_static(url, cached=None):
        return crawler.StaticFetch(
            403, url, "text/html", cf, headers={"server": "cloudflare"}
        )

    async def fake_js(url):
        big = "real content " * 60
        return 200, url, f"<html><head><title>OK</title></head><body><p>{big}</p></body></html>"

    async def allow(u):
        return True

    monkeypatch.setattr(crawler, "_fetch_static", fake_static)
    monkeypatch.setattr(crawler, "_fetch_js", fake_js)
    monkeypatch.setattr(crawler, "_allowed_by_robots", allow)
    monkeypatch.setattr(settings, "antibot_enabled", True)
    monkeypatch.setattr(settings, "escalate_on_block", True)

    res = await crawler.crawl_one("https://shop.example/x", render="auto")
    # Static was a Cloudflare challenge; the crawler escalated to the browser tier.
    assert res["render_mode"] == "js"
    assert res["title"] == "OK"
    assert res["metadata"]["block"]["vendor"] == "cloudflare"


@pytest.mark.asyncio
async def test_crawl_one_aborts_without_escalating_on_ssrf_redirect(monkeypatch):
    from app import ssrf

    js_called = {"n": 0}

    async def blocked_static(url, cached=None):
        raise ssrf.BlockedAddressError("example.com resolves to non-public address 10.0.0.1")

    async def fake_js(url):
        js_called["n"] += 1
        return 200, url, "<html><body>x</body></html>"

    async def allow(u):
        return True

    monkeypatch.setattr(crawler, "_fetch_static", blocked_static)
    monkeypatch.setattr(crawler, "_fetch_js", fake_js)
    monkeypatch.setattr(crawler, "_allowed_by_robots", allow)

    res = await crawler.crawl_one("https://evil.example/x", render="auto")
    # Must abort with an SSRF error and never escalate to the browser tier.
    assert res["error"].startswith("blocked:")
    assert res["metadata"].get("ssrf")
    assert js_called["n"] == 0


@pytest.mark.asyncio
async def test_crawl_one_skips_non_html(monkeypatch):
    async def fake_static(url, cached=None):
        return crawler.StaticFetch(200, url, "application/pdf", None)

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


@pytest.mark.asyncio
async def test_context_pool_restores_capacity_on_make_failure(monkeypatch):
    pool = crawler._ContextPool()

    async def boom():
        raise RuntimeError("launch failed")

    monkeypatch.setattr(pool, "_make", boom)
    monkeypatch.setattr(settings, "js_context_pool_size", 1)

    with pytest.raises(RuntimeError):
        await pool.acquire()
    # Capacity must be returned so the pool does not deadlock on the next acquire.
    assert pool._created == 0


def test_content_hash_stable_and_none():
    assert crawler._content_hash(None) is None
    assert crawler._content_hash("") is None
    h1 = crawler._content_hash("hello world")
    h2 = crawler._content_hash("hello world")
    assert h1 == h2 and len(h1) == 64


def test_is_fresh_logic():
    from datetime import datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    assert crawler.is_fresh({"fetched_at": recent}, 60)
    assert not crawler.is_fresh({"fetched_at": old}, 60)
    assert not crawler.is_fresh({"fetched_at": recent}, 0)  # disabled
    assert not crawler.is_fresh({"fetched_at": recent, "error": "x"}, 60)  # errors not fresh


def test_extract_structured_metadata():
    html = """
    <html lang="en"><head><title>T</title>
    <link rel="canonical" href="https://ex.com/canonical"/>
    <meta name="description" content="A description"/>
    <meta property="og:title" content="OG Title"/>
    <meta name="author" content="Jane Doe"/>
    <script type="application/ld+json">{"@type":"Article","datePublished":"2024-01-02"}</script>
    </head><body><p>body</p></body></html>
    """
    ext = crawler._extract_sync(html, "https://ex.com/page")
    m = ext.metadata
    assert m["language"] == "en"
    assert m["canonical"] == "https://ex.com/canonical"
    assert m["description"] == "A description"
    assert m["opengraph"]["title"] == "OG Title"
    assert m["author"] == "Jane Doe"
    assert m["published_at"] == "2024-01-02"
    assert m["schema_type"] == "Article"


def test_extract_jsonld_product_and_graph():
    html = """
    <html><head><title>Shoe</title>
    <script type="application/ld+json">
    {"@graph":[{"@type":"Product","name":"Runner","brand":{"name":"Acme"},
      "offers":{"@type":"Offer","price":"79.99","priceCurrency":"USD",
                "availability":"https://schema.org/InStock"}}]}
    </script></head><body><p>shoe</p></body></html>
    """
    ext = crawler._extract_sync(html, "https://shop.example/p")
    prod = ext.metadata["product"]
    assert ext.metadata["schema_type"] == "Product"
    assert prod["name"] == "Runner"
    assert prod["brand"] == "Acme"
    assert prod["price"] == "79.99"
    assert prod["currency"] == "USD"
    assert prod["availability"] == "InStock"


def test_extract_jsonld_ignores_non_string_product_fields():
    # Malformed JSON-LD must never put dict/list objects into product fields
    # (the frontend would crash rendering them).
    html = """
    <html><head><title>Bad</title>
    <script type="application/ld+json">
    {"@type":"Product","name":"X","brand":{"name":{"nested":"obj"}},
     "offers":{"price":{"x":1},"priceCurrency":["USD"],"availability":"InStock"}}
    </script></head><body><p>x</p></body></html>
    """
    ext = crawler._extract_sync(html, "https://shop.example/p")
    prod = ext.metadata.get("product", {})
    assert "brand" not in prod
    assert "price" not in prod
    assert "currency" not in prod
    assert prod.get("availability") == "InStock"  # valid string survives


def test_parse_sitemap_urlset_and_index():
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://x.com/a</loc></url>
      <url><loc>https://x.com/b</loc></url>
    </urlset>"""
    locs, is_index = crawler._parse_sitemap(urlset)
    assert is_index is False
    assert locs == ["https://x.com/a", "https://x.com/b"]

    index = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://x.com/sitemap1.xml</loc></sitemap>
    </sitemapindex>"""
    locs, is_index = crawler._parse_sitemap(index)
    assert is_index is True
    assert locs == ["https://x.com/sitemap1.xml"]


def test_parse_sitemap_handles_garbage():
    assert crawler._parse_sitemap("not xml at all") == ([], False)


@pytest.mark.asyncio
async def test_discover_sitemap_follows_index(monkeypatch):
    pages = {
        "https://x.com/sitemap.xml": (
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://x.com/sm1.xml</loc></sitemap></sitemapindex>"
        ),
        "https://x.com/sm1.xml": (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://x.com/p1</loc></url>"
            "<url><loc>https://x.com/p2</loc></url></urlset>"
        ),
    }

    async def fake_robots(url):
        return None  # no robots -> falls back to /sitemap.xml

    async def fake_fetch(url):
        return pages.get(url)

    monkeypatch.setattr(crawler, "_get_robots", fake_robots)
    monkeypatch.setattr(crawler, "_fetch_sitemap_text", fake_fetch)

    urls = await crawler.discover_sitemap_urls("https://x.com/")
    assert urls == ["https://x.com/p1", "https://x.com/p2"]


@pytest.mark.asyncio
async def test_crawl_site_seeds_from_sitemap(monkeypatch):
    async def fake_discover(start, limit=None):
        return ["https://x.com/from-sitemap"]

    async def fake_crawl_one(url, render="auto"):
        return crawler.CrawlResult(url=url, links=[], render_mode="static", error=None)

    monkeypatch.setattr(crawler, "discover_sitemap_urls", fake_discover)
    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(settings, "use_sitemap", True)

    results = await crawler.crawl_site(
        "https://x.com/", max_depth=1, max_pages=10, use_sitemap=True
    )
    urls = {r["url"] for r in results}
    assert "https://x.com" in urls  # start
    assert "https://x.com/from-sitemap" in urls  # seeded from sitemap


def test_domain_profile_snapshot():
    from app.antibot import DomainProfileStore, Tier

    store = DomainProfileStore(max_size=10)
    store.record_block("https://a.com", int(Tier.STATIC), "cloudflare")
    store.record_success("https://b.com", int(Tier.STATIC))
    snap = store.snapshot()
    by_host = {d["host"]: d for d in snap}
    assert by_host["a.com"]["engine"] == "impersonate"  # bumped past static
    assert by_host["a.com"]["last_vendor"] == "cloudflare"
    assert by_host["b.com"]["engine"] == "static"


@pytest.mark.asyncio
async def test_crawl_site_serves_fresh_from_cache(monkeypatch):
    from datetime import datetime

    fetched = datetime.now(UTC).isoformat()

    async def lookup(url):
        return {
            "url": url, "render_mode": "static", "error": None,
            "fetched_at": fetched, "links": [], "title": "cached",
        }

    async def fake_crawl_one(url, render="auto", cached=None):
        raise AssertionError("should not fetch a fresh cached page")

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(settings, "recrawl_max_age", 300.0)

    results = await crawler.crawl_site(
        "https://ex.com/x", max_depth=0, max_pages=5, cache_lookup=lookup
    )
    assert len(results) == 1
    assert results[0]["from_cache"] is True
    assert results[0]["title"] == "cached"


@pytest.mark.asyncio
async def test_crawl_site_not_modified_reuses_stored(monkeypatch):
    from datetime import datetime, timedelta

    old = (datetime.now(UTC) - timedelta(hours=5)).isoformat()

    async def lookup(url):
        return {
            "url": url, "render_mode": "static", "error": None, "fetched_at": old,
            "etag": "abc", "links": [], "title": "stored",
        }

    async def fake_crawl_one(url, render="auto", cached=None):
        assert cached == {"etag": "abc", "last_modified": None}
        return crawler.CrawlResult(
            url=url, render_mode="static", links=[], not_modified=True
        )

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)
    monkeypatch.setattr(settings, "recrawl_max_age", 60.0)

    results = await crawler.crawl_site(
        "https://ex.com/y", max_depth=0, max_pages=5, cache_lookup=lookup
    )
    assert len(results) == 1
    assert results[0]["from_cache"] is True
    assert results[0]["title"] == "stored"
