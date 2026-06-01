from app import robots
from app.fetcher import FetchResult

ROBOTS = """
User-agent: *
Disallow: /private
Crawl-delay: 2
"""


def _mock_robots(monkeypatch, body, status=200):
    async def fake_get(url, **kwargs):
        return FetchResult(status=status, final_url=url, html=body if status == 200 else None)

    monkeypatch.setattr(robots, "safe_get", fake_get)
    robots.clear_cache()


async def test_can_fetch_respects_disallow(monkeypatch):
    _mock_robots(monkeypatch, ROBOTS)
    assert await robots.can_fetch("https://example.com/public")
    assert not await robots.can_fetch("https://example.com/private/secret")


async def test_crawl_delay(monkeypatch):
    _mock_robots(monkeypatch, ROBOTS)
    assert await robots.crawl_delay("https://example.com/") == 2.0


async def test_missing_robots_allows_all(monkeypatch):
    _mock_robots(monkeypatch, "", status=404)
    assert await robots.can_fetch("https://example.com/anything")


async def test_respect_robots_disabled(monkeypatch):
    monkeypatch.setattr(robots.settings, "respect_robots", False)
    robots.clear_cache()
    assert await robots.can_fetch("https://example.com/private")
