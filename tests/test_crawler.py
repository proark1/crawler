from app import crawler
from app.fetcher import FetchResult
from app.ratelimit import HostThrottle

RICH = (
    "<html><head><title>Real</title></head><body><article><p>"
    + ("This page has plenty of real article text to extract. " * 20)
    + "</p></article></body></html>"
)
THIN = "<html><head><title>App</title></head><body><div id='root'></div></body></html>"


async def test_crawl_one_static(monkeypatch):
    async def fake_get(url, **kwargs):
        return FetchResult(status=200, final_url=url, html=RICH)

    monkeypatch.setattr(crawler, "safe_get", fake_get)
    res = await crawler.crawl_one("https://example.com/", render="static")
    assert res["status"] == 200
    assert res["render_mode"] == "static"
    assert res["text"] and "article text" in res["text"]


async def test_crawl_one_auto_falls_back_to_js(monkeypatch):
    async def fake_get(url, **kwargs):
        return FetchResult(status=200, final_url=url, html=THIN)

    async def fake_js(url):
        return 200, url, RICH

    monkeypatch.setattr(crawler, "safe_get", fake_get)
    monkeypatch.setattr(crawler, "_fetch_js", fake_js)
    res = await crawler.crawl_one("https://example.com/", render="auto")
    assert res["render_mode"] == "js"
    assert res["text"] and "article text" in res["text"]


async def test_crawl_one_robots_blocked(monkeypatch):
    async def deny(url):
        return False

    monkeypatch.setattr(crawler.robots, "can_fetch", deny)
    res = await crawler.crawl_one("https://example.com/", check_robots=True)
    assert res["error"] == "blocked by robots.txt"


async def test_crawl_site_bfs_respects_max_pages(monkeypatch):
    monkeypatch.setattr(crawler, "_throttle", HostThrottle(0))

    async def allow(url):
        return True

    async def no_delay(url):
        return None

    monkeypatch.setattr(crawler.robots, "can_fetch", allow)
    monkeypatch.setattr(crawler.robots, "crawl_delay", no_delay)

    async def fake_crawl_one(url, render="auto"):
        n = url.rstrip("/").split("/")[-1] or "0"
        links = [f"https://example.com/{int(n) + i}" for i in range(1, 4)] if n.isdigit() else []
        return {"url": url, "links": links, "render_mode": "static", "metadata": {},
                "status": 200, "error": None}

    monkeypatch.setattr(crawler, "crawl_one", fake_crawl_one)

    seen = []

    async def on_page(r):
        seen.append(r)

    results = await crawler.crawl_site(
        "https://example.com/0", max_depth=3, max_pages=5, on_page=on_page
    )
    assert len(results) == 5  # capped
    assert len({r["url"] for r in results}) == 5  # deduped
    assert len(seen) == 5  # on_page fired for each
