from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from . import db, jobs
from .auth import require_api_key
from .config import settings
from .crawler import close_browser, crawl_one, crawl_site
from .observability import configure_logging, metrics


class CrawlRequest(BaseModel):
    url: HttpUrl
    render: Literal["auto", "static", "js"] = "auto"
    follow_links: bool = False
    max_depth: int = Field(1, ge=0, le=settings.max_depth_hard_limit)
    max_pages: int = Field(10, ge=1, le=settings.max_pages_hard_limit)
    same_host_only: bool = True
    store: bool = True


class PageOut(BaseModel):
    id: int | None = None
    url: str
    final_url: str | None = None
    status: int | None = None
    title: str | None = None
    text: str | None = None
    markdown: str | None = None
    links: list[str] = []
    metadata: dict = {}
    render_mode: str
    error: str | None = None
    fetched_at: str | None = None


class CrawlResponse(BaseModel):
    pages: list[PageOut]
    count: int


class JobStartResponse(BaseModel):
    job_id: int


class JobStatusResponse(BaseModel):
    id: int
    status: str
    total: int
    error: str | None = None
    params: dict = {}
    created_at: str | None = None
    updated_at: str | None = None
    pages: list[PageOut] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await db.init_pool()
    try:
        yield
    finally:
        await jobs.shutdown()
        await close_browser()
        await db.close_pool()


app = FastAPI(title="Crawler", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    metrics.inc("crawler_requests_total", method=request.method, path=path,
                status=str(response.status_code))
    metrics.inc("crawler_request_seconds_sum", elapsed, path=path)
    return response


@app.get("/health")
async def health() -> dict:
    """Liveness: 200 while the process is up (used by the platform healthcheck)."""
    return {"status": "ok", "db": await db.ping()}


@app.get("/readyz")
async def readyz(response: Response) -> dict:
    """Readiness: 503 when the database is unreachable."""
    ok = await db.ping()
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "unavailable", "db": ok}


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> str:
    return metrics.render()


def _to_page_out(d: dict) -> PageOut:
    return PageOut(
        id=d.get("id"),
        url=d["url"],
        final_url=d.get("final_url"),
        status=d.get("status"),
        title=d.get("title"),
        text=d.get("text"),
        markdown=d.get("markdown"),
        links=d.get("links") or [],
        metadata=d.get("metadata") or {},
        render_mode=d["render_mode"],
        error=d.get("error"),
        fetched_at=d.get("fetched_at"),
    )


async def _store_results(results: list[dict]) -> list[dict]:
    """Persist each result, tolerating individual failures (partial success)."""
    saved = await asyncio.gather(
        *(db.upsert_page(r) for r in results), return_exceptions=True
    )
    out: list[dict] = []
    for original, result in zip(results, saved, strict=True):
        if isinstance(result, Exception):
            metrics.inc("crawler_store_errors_total")
            fallback = dict(original)
            fallback.setdefault("metadata", {})["store_error"] = str(result)
            out.append(fallback)
        else:
            out.append(result)
    return out


@app.post("/crawl", response_model=CrawlResponse, dependencies=[Depends(require_api_key)])
async def crawl(req: CrawlRequest) -> CrawlResponse:
    url = str(req.url)
    if req.follow_links:
        results = await crawl_site(
            url,
            render=req.render,
            max_depth=req.max_depth,
            max_pages=req.max_pages,
            same_host_only=req.same_host_only,
        )
    else:
        results = [await crawl_one(url, render=req.render, check_robots=True)]

    metrics.inc("crawler_pages_total", len(results))

    if req.store:
        stored = await _store_results(results)
    else:
        stored = [dict(r) for r in results]
    for s in stored:
        s.pop("html", None)

    return CrawlResponse(pages=[_to_page_out(p) for p in stored], count=len(stored))


@app.post("/jobs", response_model=JobStartResponse, dependencies=[Depends(require_api_key)])
async def start_job(req: CrawlRequest) -> JobStartResponse:
    params = req.model_dump(mode="json")
    job_id = await jobs.start(params)
    return JobStartResponse(job_id=job_id)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse,
         dependencies=[Depends(require_api_key)])
async def get_job(job_id: int) -> JobStatusResponse:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    pages = await db.get_job_pages(job_id)
    return JobStatusResponse(
        id=job["id"],
        status=job["status"],
        total=job["total"],
        error=job.get("error"),
        params=job.get("params") or {},
        created_at=job.get("created_at"),
        updated_at=job.get("updated_at"),
        pages=[_to_page_out(p) for p in pages],
    )


@app.get("/jobs/{job_id}/events", dependencies=[Depends(require_api_key)])
async def job_events(job_id: int) -> StreamingResponse:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def stream() -> AsyncIterator[str]:
        # Snapshot of whatever is already persisted, so late subscribers catch up.
        existing = await db.get_job_pages(job_id)
        yield _sse({"type": "snapshot",
                    "pages": [_to_page_out(p).model_dump() for p in existing],
                    "status": job["status"]})

        channel = jobs.get_channel(job_id)
        if channel is None:
            # Job already finished before this connection; nothing more to stream.
            yield _sse({"type": "done", "status": job["status"], "total": job["total"]})
            return

        queue = await channel.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"  # comment frame keeps the connection open
                    continue
                yield _sse(event)
                if event.get("type") == "done":
                    break
        finally:
            channel.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.get("/pages", response_model=list[PageOut], dependencies=[Depends(require_api_key)])
async def list_pages(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[PageOut]:
    rows = await db.list_pages(limit=limit, offset=offset)
    return [_to_page_out(r) for r in rows]


@app.get("/pages/search", response_model=list[PageOut],
         dependencies=[Depends(require_api_key)])
async def search_pages(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
) -> list[PageOut]:
    rows = await db.search_pages(q, limit=limit)
    return [_to_page_out(r) for r in rows]


@app.get("/pages/by-url", response_model=PageOut, dependencies=[Depends(require_api_key)])
async def get_page_by_url(url: str) -> PageOut:
    row = await db.get_page_by_url(url)
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    row.pop("html", None)
    return _to_page_out(row)


@app.get("/pages/{page_id}", response_model=PageOut, dependencies=[Depends(require_api_key)])
async def get_page(page_id: int) -> PageOut:
    row = await db.get_page_by_id(page_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    row.pop("html", None)
    return _to_page_out(row)
