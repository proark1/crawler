from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from . import crawler, db, jobs, observability
from .auth import require_api_key
from .config import settings
from .crawler import close_browser, crawl_one, crawl_site
from .ratelimit import RateLimitMiddleware

log = logging.getLogger("crawler.api")


class CrawlRequest(BaseModel):
    url: HttpUrl
    render: Literal["auto", "static", "js"] = "auto"
    follow_links: bool = False
    max_depth: int = Field(1, ge=0, le=5)
    max_pages: int = Field(10, ge=1, le=100)
    same_host_only: bool = True
    store: bool = True
    webhook_url: HttpUrl | None = None


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


class JobOut(BaseModel):
    id: str
    status: str
    progress: int
    total: int | None = None
    count: int
    pages: list[PageOut] = []
    error: str | None = None


class JobSummary(BaseModel):
    id: str
    status: str
    progress: int
    total: int | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.configure_logging()
    observability.init_sentry()
    if settings.is_production and not settings.api_key:
        raise RuntimeError(
            "Refusing to start in production with auth disabled: set API_KEY."
        )
    try:
        await db.init_pool()
    except Exception as exc:  # noqa: BLE001 -- start degraded; /health will report it
        log.error("database init failed at startup: %s", exc)
    try:
        yield
    finally:
        await jobs.cancel_all()
        await close_browser()
        await db.close_pool()


app = FastAPI(title="Crawler", version="0.3.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["X-Total-Count"],
)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    observability.record_http(
        request.method, request.url.path, response.status_code
    )
    return response


@app.get("/health")
async def health() -> dict:
    db_ok = await db.ping()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@app.get("/metrics")
async def metrics() -> Response:
    if not observability.metrics_enabled():
        raise HTTPException(status_code=404, detail="metrics disabled")
    body, content_type = observability.render_metrics()
    return Response(content=body, media_type=content_type)


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


def _make_cache_lookup(store: bool):
    if not store:
        return None

    async def lookup(url: str) -> dict | None:
        try:
            return await db.get_page_by_url(url)
        except Exception:  # noqa: BLE001 -- caching is best-effort
            return None

    return lookup


async def _run_crawl(req: CrawlRequest) -> list[dict]:
    url = str(req.url)
    if req.follow_links:
        results = await crawl_site(
            url,
            render=req.render,
            max_depth=req.max_depth,
            max_pages=req.max_pages,
            same_host_only=req.same_host_only,
            cache_lookup=_make_cache_lookup(req.store),
        )
    else:
        cached = None
        if req.store:
            lookup = _make_cache_lookup(True)
            row = await lookup(url) if lookup else None
            if row and crawler.is_fresh(row, settings.recrawl_max_age):
                return [{**row, "from_cache": True}]
            if row:
                cached = {"etag": row.get("etag"), "last_modified": row.get("last_modified")}
        if cached:
            res = await crawl_one(url, render=req.render, cached=cached)
        else:
            res = await crawl_one(url, render=req.render)
        if res.get("not_modified") and req.store:
            row = await db.get_page_by_url(url)
            results = [row or res]
        else:
            results = [res]

    observability.record_pages(results)

    # Persist freshly crawled pages (skip rows that came straight from cache).
    to_store = [r for r in results if not r.get("from_cache")]
    if req.store and to_store:
        stored = await asyncio.gather(*(db.upsert_page(r) for r in to_store))
        stored_by_url = {s["url"]: s for s in stored}
        results = [stored_by_url.get(r["url"], r) for r in results]
    for r in results:
        r.pop("html", None)
    return [dict(r) for r in results]


class _nullctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@app.post("/crawl", response_model=CrawlResponse, dependencies=[Depends(require_api_key)])
async def crawl(req: CrawlRequest) -> CrawlResponse:
    """Synchronous crawl. Best for single pages or small follow-link crawls."""
    timer = observability.CRAWL_DURATION.time() if observability.CRAWL_DURATION else _nullctx()
    with timer:
        stored = await _run_crawl(req)
    return CrawlResponse(pages=[_to_page_out(p) for p in stored], count=len(stored))


@app.post(
    "/crawl/jobs",
    response_model=JobOut,
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def create_crawl_job(req: CrawlRequest) -> JobOut:
    """Submit a crawl that runs in the background; poll /crawl/jobs/{id} for results."""
    job = await jobs.create_job(
        request=json.loads(req.model_dump_json()),
        webhook_url=str(req.webhook_url) if req.webhook_url else None,
    )
    job.total = req.max_pages if req.follow_links else 1

    async def runner() -> None:
        await jobs.mark(job, status="running")
        try:
            stored = await _run_crawl(req)
            await jobs.mark(job, pages=stored, progress=len(stored), status="done")
        except asyncio.CancelledError:
            await jobs.mark(job, status="error", error="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            await jobs.mark(job, status="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            await jobs.fire_webhook(job)

    job._task = asyncio.create_task(runner())
    return JobOut(id=job.id, status=job.status, progress=0, total=job.total, count=0)


@app.get(
    "/crawl/jobs",
    response_model=list[JobSummary],
    dependencies=[Depends(require_api_key)],
)
async def list_crawl_jobs(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> list[JobSummary]:
    rows = await db.list_jobs(limit=limit, offset=offset)
    return [
        JobSummary(
            id=r["id"],
            status=r["status"],
            progress=r.get("progress", 0),
            total=r.get("total"),
            error=r.get("error"),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in rows
    ]


@app.get(
    "/crawl/jobs/{job_id}",
    response_model=JobOut,
    dependencies=[Depends(require_api_key)],
)
async def get_crawl_job(job_id: str) -> JobOut:
    data = await jobs.load_public(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(
        id=data["id"],
        status=data["status"],
        progress=data["progress"],
        total=data["total"],
        count=data["count"],
        pages=[_to_page_out(p) for p in data["pages"]],
        error=data["error"],
    )


@app.get(
    "/crawl/jobs/{job_id}/stream",
    dependencies=[Depends(require_api_key)],
)
async def stream_crawl_job(job_id: str) -> StreamingResponse:
    """Server-Sent Events stream of a job's progress until it reaches a terminal state."""

    async def event_gen():
        last = None
        for _ in range(600):  # hard cap ~10 min
            data = await jobs.load_public(job_id)
            if data is None:
                yield 'event: error\ndata: {"error":"not found"}\n\n'
                return
            snapshot = (data["status"], data["progress"])
            if snapshot != last:
                last = snapshot
                yield f"data: {json.dumps(data, default=str)}\n\n"
            if data["status"] in ("done", "error"):
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/pages", response_model=list[PageOut], dependencies=[Depends(require_api_key)])
async def list_pages(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[PageOut]:
    rows, total = await asyncio.gather(
        db.list_pages(limit=limit, offset=offset), db.count_pages()
    )
    response.headers["X-Total-Count"] = str(total)
    return [_to_page_out(r) for r in rows]


@app.get("/pages/export", dependencies=[Depends(require_api_key)])
async def export_pages(
    format: Literal["json", "csv", "md"] = Query("json"),
) -> StreamingResponse:
    """Stream every stored page as JSON, CSV, or Markdown."""
    if format == "csv":
        async def gen_csv():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["id", "url", "title", "status", "render_mode", "fetched_at"])
            yield buf.getvalue()
            async for p in db.iter_all_pages():
                buf.seek(0)
                buf.truncate(0)
                writer.writerow([
                    p.get("id"), p.get("url"), p.get("title") or "",
                    p.get("status") or "", p.get("render_mode") or "",
                    p.get("fetched_at") or "",
                ])
                yield buf.getvalue()

        return StreamingResponse(
            gen_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=pages.csv"},
        )

    if format == "md":
        async def gen_md():
            yield "# Crawled pages\n\n"
            async for p in db.iter_all_pages():
                title = p.get("title") or p.get("url")
                yield f"- [{title}]({p.get('url')}) — {p.get('status') or '—'}\n"

        return StreamingResponse(
            gen_md(),
            media_type="text/markdown",
            headers={"Content-Disposition": "attachment; filename=pages.md"},
        )

    async def gen_json():
        first = True
        yield "["
        async for p in db.iter_all_pages():
            yield ("" if first else ",") + json.dumps(p, default=str)
            first = False
        yield "]"

    return StreamingResponse(
        gen_json(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=pages.json"},
    )


@app.get(
    "/pages/search",
    response_model=list[PageOut],
    dependencies=[Depends(require_api_key)],
)
async def search_pages(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
) -> list[PageOut]:
    rows = await db.search_pages(q, limit=limit)
    return [_to_page_out(r) for r in rows]


@app.get(
    "/pages/by-url",
    response_model=PageOut,
    dependencies=[Depends(require_api_key)],
)
async def get_page_by_url(url: str) -> PageOut:
    row = await db.get_page_by_url(url)
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    row.pop("html", None)
    return _to_page_out(row)


@app.get(
    "/pages/{page_id}",
    response_model=PageOut,
    dependencies=[Depends(require_api_key)],
)
async def get_page(page_id: int) -> PageOut:
    row = await db.get_page_by_id(page_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    row.pop("html", None)
    return _to_page_out(row)


@app.get(
    "/pages/{page_id}/html",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_page_raw_html(page_id: int) -> PlainTextResponse:
    html = await db.get_page_html(page_id)
    if html is None:
        raise HTTPException(status_code=404, detail="No stored HTML for this page")
    return PlainTextResponse(html, media_type="text/html")


@app.delete(
    "/pages/{page_id}",
    status_code=204,
    dependencies=[Depends(require_api_key)],
)
async def delete_page(page_id: int) -> Response:
    deleted = await db.delete_page(page_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Page not found")
    return Response(status_code=204)
