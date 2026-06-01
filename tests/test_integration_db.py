"""Integration tests that require a real Postgres.

Skipped unless RUN_DB_TESTS=1 (set in CI, where a Postgres service is available).
They exercise migrations, full-text search ranking, page CRUD, the compressed
HTML round-trip, and durable job persistence against the actual database.
"""
from __future__ import annotations

import os

import pytest

RUN = os.getenv("RUN_DB_TESTS") == "1"
pytestmark = [
    pytest.mark.skipif(not RUN, reason="set RUN_DB_TESTS=1 with a live Postgres"),
    pytest.mark.asyncio,
]


@pytest.fixture(autouse=True)
async def _clean_db():
    from app import db

    await db.init_pool()
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE pages RESTART IDENTITY")
        await conn.execute("TRUNCATE crawl_jobs")
    yield
    await db.close_pool()


def _page(url: str, title: str, text: str) -> dict:
    return {
        "url": url, "final_url": url, "status": 200, "title": title,
        "text": text, "markdown": f"# {title}", "html": f"<h1>{title}</h1>",
        "links": ["https://x.com/a"], "metadata": {"k": "v"},
        "render_mode": "static", "error": None, "etag": "e1",
        "last_modified": "Mon, 01 Jan 2026 00:00:00 GMT", "content_hash": "h1",
    }


async def test_migrations_create_expected_tables():
    from app import db

    async with db.acquire() as conn:
        applied = await conn.fetchval("SELECT count(*) FROM schema_migrations")
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='pages'"
        )
    names = {c["column_name"] for c in cols}
    assert applied >= 4
    assert {"markdown", "etag", "last_modified", "content_hash", "html_gz", "search_tsv"} <= names
    assert "html" not in names  # dropped in migration 3


async def test_upsert_search_and_html_roundtrip():
    from app import db

    await db.upsert_page(_page("https://x.com/python", "Python guide", "asyncio coroutines tutorial"))
    await db.upsert_page(_page("https://x.com/rust", "Rust guide", "ownership borrow checker"))

    assert await db.count_pages() == 2

    hits = await db.search_pages("coroutines", limit=10)
    assert len(hits) == 1 and hits[0]["url"] == "https://x.com/python"

    row = await db.get_page_by_url("https://x.com/python")
    assert row["markdown"] == "# Python guide"
    pid = row["id"]
    html = await db.get_page_html(pid)
    assert html == "<h1>Python guide</h1>"  # gzip round-trip

    assert await db.delete_page(pid) is True
    assert await db.get_page_by_id(pid) is None


async def test_upsert_is_idempotent_on_url():
    from app import db

    await db.upsert_page(_page("https://x.com/dup", "v1", "first"))
    await db.upsert_page(_page("https://x.com/dup", "v2", "second"))
    assert await db.count_pages() == 1
    row = await db.get_page_by_url("https://x.com/dup")
    assert row["title"] == "v2"


async def test_job_persistence_roundtrip():
    from app import db

    await db.upsert_job({
        "id": "job1", "status": "running", "progress": 1, "total": 5,
        "request": {"url": "https://x.com"}, "pages": [], "error": None,
        "webhook_url": None,
    })
    await db.upsert_job({
        "id": "job1", "status": "done", "progress": 5, "total": 5,
        "request": {"url": "https://x.com"}, "pages": [{"url": "https://x.com"}],
        "error": None, "webhook_url": None,
    })
    row = await db.get_job_row("job1")
    assert row["status"] == "done" and row["progress"] == 5
    assert len(row["pages"]) == 1
    jobs_list = await db.list_jobs()
    assert any(j["id"] == "job1" for j in jobs_list)


async def test_reap_orphaned_jobs():
    from app import db

    await db.upsert_job({
        "id": "stuck", "status": "running", "progress": 1, "total": 5,
        "request": {}, "pages": [], "error": None, "webhook_url": None,
    })
    reaped = await db.reap_orphaned_jobs()
    assert reaped >= 1
    row = await db.get_job_row("stuck")
    assert row["status"] == "error"
    assert "orphaned" in row["error"]
