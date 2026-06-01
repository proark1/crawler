"""Tier 3 challenge solver via FlareSolverr.

FlareSolverr (https://github.com/FlareSolverr/FlareSolverr) is a self-hostable
proxy that drives a real browser to pass Cloudflare/DDoS-Guard interstitials and
returns the solved HTML plus the clearance cookies. We POST to its `/v1`
endpoint; the engine is only used when `FLARESOLVERR_URL` is configured.
"""
from __future__ import annotations

import httpx

from .config import settings


class SolverUnavailable(Exception):
    """Raised when no solver endpoint is configured."""


class SolverResult:
    def __init__(self, status: int, url: str, html: str, cookies: list[dict]):
        self.status = status
        self.url = url
        self.html = html
        self.cookies = cookies


async def solve(url: str, proxy: str | None = None) -> SolverResult:
    """Resolve a challenge-protected URL through FlareSolverr."""
    endpoint = settings.flaresolverr_url
    if not endpoint:
        raise SolverUnavailable("FLARESOLVERR_URL not configured")

    payload: dict = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": int(settings.flaresolverr_timeout * 1000),
    }
    if proxy:
        payload["proxy"] = {"url": proxy}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.flaresolverr_timeout + 10)
    ) as client:
        resp = await client.post(endpoint.rstrip("/") + "/v1", json=payload)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "ok":
        raise httpx.HTTPError(f"flaresolverr: {data.get('message', 'failed')}")
    solution = data.get("solution") or {}
    return SolverResult(
        status=int(solution.get("status") or 200),
        url=solution.get("url") or url,
        html=solution.get("response") or "",
        cookies=solution.get("cookies") or [],
    )
