from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from . import db
from .crawler import crawl_one, crawl_site


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(title="Crawler", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


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


@app.post("/crawl", response_model=CrawlResponse)
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
        results = [await crawl_one(url, render=req.render)]

    stored: list[dict] = []
    for r in results:
        # Drop heavy raw HTML from response payload, but keep it in DB.
        if req.store:
            saved = await db.upsert_page(r)
            saved.pop("html", None)
            stored.append(saved)
        else:
            r = dict(r)
            r.pop("html", None)
            stored.append(r)

    return CrawlResponse(pages=[_to_page_out(p) for p in stored], count=len(stored))


@app.get("/pages", response_model=list[PageOut])
async def list_pages(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[PageOut]:
    rows = await db.list_pages(limit=limit, offset=offset)
    return [_to_page_out(r) for r in rows]


@app.get("/pages/by-url", response_model=PageOut)
async def get_page_by_url(url: str) -> PageOut:
    row = await db.get_page_by_url(url)
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    row.pop("html", None)
    return _to_page_out(row)


@app.get("/pages/{page_id}", response_model=PageOut)
async def get_page(page_id: int) -> PageOut:
    row = await db.get_page_by_id(page_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    row.pop("html", None)
    return _to_page_out(row)
