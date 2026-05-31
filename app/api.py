from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

from . import db, jobs
from .auth import require_api_key
from .config import settings
from .crawler import close_browser, crawl_one, crawl_site


class CrawlRequest(BaseModel):
    url: HttpUrl
    render: Literal["auto", "static", "js"] = "auto"
    follow_links: bool = False
    max_depth: int = Field(1, ge=0, le=5)
    max_pages: int = Field(10, ge=1, le=100)
    same_host_only: bool = True
    store: bool = True


class PageOut(BaseModel):
    id: int | None = None
    url: str
    final_url: str | None = None
    status: int | None = None
    title: str | None = None
    text: str | None = None
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    try:
        yield
    finally:
        await jobs.cancel_all()
        await close_browser()
        await db.close_pool()


app = FastAPI(title="Crawler", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["X-Total-Count"],
)


@app.get("/health")
async def health() -> dict:
    db_ok = await db.ping()
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


def _to_page_out(d: dict) -> PageOut:
    return PageOut(
        id=d.get("id"),
        url=d["url"],
        final_url=d.get("final_url"),
        status=d.get("status"),
        title=d.get("title"),
        text=d.get("text"),
        links=d.get("links") or [],
        metadata=d.get("metadata") or {},
        render_mode=d["render_mode"],
        error=d.get("error"),
        fetched_at=d.get("fetched_at"),
    )


async def _run_crawl(req: CrawlRequest) -> list[dict]:
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
        results = [await crawl_one(url, render=req.render)]

    # Drop heavy raw HTML from response payload, but keep it in DB.
    if req.store:
        stored = await asyncio.gather(*(db.upsert_page(r) for r in results))
    else:
        stored = [dict(r) for r in results]
    for s in stored:
        s.pop("html", None)
    return stored


@app.post("/crawl", response_model=CrawlResponse, dependencies=[Depends(require_api_key)])
async def crawl(req: CrawlRequest) -> CrawlResponse:
    """Synchronous crawl. Best for single pages or small follow-link crawls."""
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
    job = await jobs.create_job()
    job.total = req.max_pages if req.follow_links else 1

    async def runner() -> None:
        job.status = "running"
        job.updated_at = time.time()
        try:
            stored = await _run_crawl(req)
            job.pages = stored
            job.progress = len(stored)
            job.status = "done"
        except asyncio.CancelledError:
            job.status = "error"
            job.error = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.updated_at = time.time()

    job._task = asyncio.create_task(runner())
    return JobOut(id=job.id, status=job.status, progress=0, total=job.total, count=0)


@app.get(
    "/crawl/jobs/{job_id}",
    response_model=JobOut,
    dependencies=[Depends(require_api_key)],
)
async def get_crawl_job(job_id: str) -> JobOut:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    data = job.public()
    return JobOut(
        id=data["id"],
        status=data["status"],
        progress=data["progress"],
        total=data["total"],
        count=data["count"],
        pages=[_to_page_out(p) for p in data["pages"]],
        error=data["error"],
    )


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
