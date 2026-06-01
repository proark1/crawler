import httpx
import respx

from app import fetcher
from app.config import settings

PUB = "http://93.184.216.34"  # literal public IP -> no DNS lookup in the SSRF guard


@respx.mock
async def test_safe_get_returns_html_and_status():
    await fetcher.close_client()
    respx.get(f"{PUB}/").mock(
        return_value=httpx.Response(200, html="<html><title>Hi</title></html>")
    )
    res = await fetcher.safe_get(f"{PUB}/", block_private=True)
    assert res.status == 200
    assert res.html and "Hi" in res.html


@respx.mock
async def test_safe_get_captures_error_status():
    await fetcher.close_client()
    respx.get(f"{PUB}/missing").mock(return_value=httpx.Response(404, html="<html>nope</html>"))
    res = await fetcher.safe_get(f"{PUB}/missing", block_private=True)
    assert res.status == 404  # status preserved instead of lost to an exception


@respx.mock
async def test_safe_get_skips_non_html():
    await fetcher.close_client()
    respx.get(f"{PUB}/file.pdf").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        )
    )
    res = await fetcher.safe_get(f"{PUB}/file.pdf", block_private=True)
    assert res.html is None
    assert "skipped" in res.meta


@respx.mock
async def test_safe_get_enforces_size_cap(monkeypatch):
    await fetcher.close_client()
    monkeypatch.setattr(settings, "max_response_bytes", 100)
    big = "<html>" + ("a" * 5000) + "</html>"
    respx.get(f"{PUB}/big").mock(
        return_value=httpx.Response(
            200, content=big.encode(), headers={"content-type": "text/html"}
        )
    )
    res = await fetcher.safe_get(f"{PUB}/big", block_private=True)
    assert res.truncated is True
    assert res.html is not None and len(res.html) <= 100


@respx.mock
async def test_safe_get_blocks_redirect_to_private():
    await fetcher.close_client()
    respx.get(f"{PUB}/redir").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    res = await fetcher.safe_get(f"{PUB}/redir", block_private=True)
    assert res.error and "blocked" in res.error
