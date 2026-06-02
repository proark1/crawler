from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Literal

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from . import db, jobs, observability, service
from .auth import require_api_key
from .config import settings
from .crawler import close_browser
from .lrucache import BoundedLRU
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
    use_sitemap: bool = True
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
        reaped = await db.reap_orphaned_jobs()
        if reaped:
            log.info("reaped %d orphaned job(s) from a previous run", reaped)
    except Exception as exc:  # noqa: BLE001 -- start degraded; /health will report it
        log.error("database init failed at startup: %s", exc)
    try:
        yield
    finally:
        await jobs.cancel_all()
        await close_browser()
        await db.close_pool()


# Source the OpenAPI version from package metadata so /docs, /redoc, and
# /openapi.json never drift behind the version declared in pyproject.toml.
try:
    _API_VERSION = _pkg_version("crawler")
except PackageNotFoundError:  # not installed (e.g. running from a source checkout)
    _API_VERSION = "0.5.0"

app = FastAPI(title="Crawler", version=_API_VERSION, lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["X-Total-Count"],
)


@app.exception_handler(asyncpg.PostgresError)
async def _pg_error_handler(request: Request, exc: asyncpg.PostgresError) -> JSONResponse:
    log.error("database error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(asyncio.TimeoutError)
async def _timeout_handler(request: Request, exc: asyncio.TimeoutError) -> JSONResponse:
    # Most commonly a pool-acquire timeout under saturation.
    log.error("timeout on %s", request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Service busy, try again"})


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    # Use the matched route template (e.g. "/pages/{page_id}") rather than the
    # concrete path so per-id requests don't explode Prometheus label cardinality.
    route = request.scope.get("route")
    path = getattr(route, "path", None) or "other"
    observability.record_http(request.method, path, response.status_code)
    return response


# Defined last so it wraps routing: strip an optional "/v1" prefix so every
# endpoint is reachable at both "/x" and "/v1/x" without duplicating routes.
_VERSION_PREFIX = f"/{settings.api_version}"


@app.middleware("http")
async def _version_prefix_middleware(request: Request, call_next):
    path = request.scope.get("path", "")
    if path == _VERSION_PREFIX or path.startswith(_VERSION_PREFIX + "/"):
        stripped = path[len(_VERSION_PREFIX):] or "/"
        request.scope["path"] = stripped
        request.scope["raw_path"] = stripped.encode()
    return await call_next(request)


@app.get("/health")
async def health() -> dict:
    """Liveness: 200 while the process is up; reports DB connectivity informationally."""
    db_ok = await db.ping()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@app.get("/ready")
async def ready(response: Response) -> dict:
    """Readiness: 503 when the database is unreachable, so orchestrators hold traffic."""
    db_ok = await db.ping()
    if not db_ok:
        response.status_code = 503
    return {"status": "ready" if db_ok else "unready", "database": db_ok}


class StatsResponse(BaseModel):
    total: int
    errors: int
    blocked: int


@app.get("/stats", response_model=StatsResponse, dependencies=[Depends(require_api_key)])
async def stats() -> StatsResponse:
    """Index aggregates: total stored pages, errored pages, and bot-blocked pages."""
    return StatsResponse(**await db.stats())


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


async def _run_crawl(req: CrawlRequest, on_progress=None) -> list[dict]:
    return await service.run_crawl(
        url=str(req.url),
        render=req.render,
        follow_links=req.follow_links,
        max_depth=req.max_depth,
        max_pages=req.max_pages,
        same_host_only=req.same_host_only,
        store=req.store,
        use_sitemap=req.use_sitemap,
        on_progress=on_progress,
    )


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


# Idempotency-Key -> job id, so a retried submission returns the same job
# instead of starting a duplicate crawl.
_idempotency: BoundedLRU[str, str] = BoundedLRU(2048)


async def _start_job(req: CrawlRequest) -> jobs.Job:
    job = await jobs.create_job(
        request=json.loads(req.model_dump_json()),
        webhook_url=str(req.webhook_url) if req.webhook_url else None,
    )
    job.total = req.max_pages if req.follow_links else 1

    def bump(_res) -> None:
        import time as _t

        job.progress += 1
        job.updated_at = _t.time()

    async def runner() -> None:
        await jobs.mark(job, status="running")
        try:
            stored = await _run_crawl(req, on_progress=bump)
            await jobs.mark(job, pages=stored, progress=len(stored), status="done")
        except asyncio.CancelledError:
            await jobs.mark(job, status="cancelled", error="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            await jobs.mark(job, status="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            await jobs.fire_webhook(job)

    job._task = asyncio.create_task(runner())
    return job


class BatchCrawlRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=50)
    render: Literal["auto", "static", "js"] = "auto"
    follow_links: bool = False
    max_depth: int = Field(1, ge=0, le=5)
    max_pages: int = Field(10, ge=1, le=100)
    same_host_only: bool = True
    store: bool = True
    use_sitemap: bool = True
    webhook_url: HttpUrl | None = None


class BatchJobOut(BaseModel):
    jobs: list[dict]


@app.post(
    "/crawl/jobs",
    response_model=JobOut,
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def create_crawl_job(req: CrawlRequest, request: Request) -> JobOut:
    """Submit a crawl that runs in the background; poll /crawl/jobs/{id} for results.

    Pass an ``Idempotency-Key`` header to make retries safe: the same key returns
    the original job instead of starting a duplicate crawl.
    """
    idem = request.headers.get("idempotency-key")
    if idem:
        existing_id = _idempotency.get(idem)
        if existing_id and (existing := jobs.get_job(existing_id)) is not None:
            return JobOut(id=existing.id, status=existing.status, progress=existing.progress,
                          total=existing.total, count=len(existing.pages))

    job = await _start_job(req)
    if idem:
        _idempotency.set(idem, job.id)
    return JobOut(id=job.id, status=job.status, progress=0, total=job.total, count=0)


@app.post(
    "/crawl/batch",
    response_model=BatchJobOut,
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def create_batch_crawl(req: BatchCrawlRequest) -> BatchJobOut:
    """Submit many URLs at once; each becomes its own background job."""
    shared = req.model_dump(exclude={"urls"})
    out = []
    for url in req.urls:
        single = CrawlRequest(url=url, **shared)
        job = await _start_job(single)
        out.append({"url": str(url), "job_id": job.id})
    return BatchJobOut(jobs=out)


@app.get(
    "/crawl/jobs",
    response_model=list[JobSummary],
    dependencies=[Depends(require_api_key)],
)
async def list_crawl_jobs(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> list[JobSummary]:
    """List recent background crawl jobs, newest first."""
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
    """Fetch a job's status and (when finished) its crawled pages.

    The embedded ``pages`` list is capped at ``job_pages_inline_limit``; ``count``
    always reflects the true total. Use /pages or /pages/export for the full set.
    """
    data = await jobs.load_public(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found")
    inline_pages = data["pages"][: settings.job_pages_inline_limit]
    return JobOut(
        id=data["id"],
        status=data["status"],
        progress=data["progress"],
        total=data["total"],
        count=data["count"],
        pages=[_to_page_out(p) for p in inline_pages],
        error=data["error"],
    )


@app.delete(
    "/crawl/jobs/{job_id}",
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def cancel_crawl_job(job_id: str) -> dict:
    """Cancel a running background job. 404 if unknown; 409 if already finished."""
    if jobs.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cancelled = await jobs.cancel(job_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Job already finished")
    return {"id": job_id, "status": "cancelled"}


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


class DomainProfileOut(BaseModel):
    host: str
    min_tier: int
    engine: str
    successes: int
    blocks: int
    last_vendor: str | None = None
    last_block_at: float | None = None


@app.get(
    "/domains",
    response_model=list[DomainProfileOut],
    dependencies=[Depends(require_api_key)],
)
async def list_domains(limit: int = Query(200, ge=1, le=1000)) -> list[DomainProfileOut]:
    """The anti-bot strategy the crawler learned per domain (engine tier, blocks)."""
    from .antibot import profiles

    return [DomainProfileOut(**d) for d in profiles.snapshot(limit=limit)]


@app.get("/pages", response_model=list[PageOut], dependencies=[Depends(require_api_key)])
async def list_pages(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[PageOut]:
    """List stored pages, newest first. Total count is in the `X-Total-Count` header."""
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
    """Ranked full-text search over stored page titles and text (URL ILIKE fallback)."""
    rows = await db.search_pages(q, limit=limit)
    return [_to_page_out(r) for r in rows]


@app.get(
    "/pages/by-url",
    response_model=PageOut,
    dependencies=[Depends(require_api_key)],
)
async def get_page_by_url(url: str) -> PageOut:
    """Fetch a single stored page by its exact (normalized) URL."""
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
    """Fetch a single stored page by id."""
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
    """Return the stored (decompressed) raw HTML for a page."""
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
    """Delete a stored page by id."""
    deleted = await db.delete_page(page_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Page not found")
    return Response(status_code=204)
