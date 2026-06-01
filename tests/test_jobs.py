from __future__ import annotations

import time

import pytest

from app import jobs


@pytest.mark.asyncio
async def test_create_and_get_job():
    job = await jobs.create_job()
    assert job.status == "pending"
    assert jobs.get_job(job.id) is job
    assert jobs.get_job("nonexistent") is None


@pytest.mark.asyncio
async def test_job_public_shape():
    job = await jobs.create_job()
    job.status = "done"
    job.pages = [{"url": "https://ex.com"}]
    job.progress = 1
    data = job.public()
    assert data["status"] == "done"
    assert data["count"] == 1
    assert data["pages"][0]["url"] == "https://ex.com"


@pytest.mark.asyncio
async def test_prune_drops_stale_finished_jobs(monkeypatch):
    job = await jobs.create_job()
    job.status = "done"
    job.updated_at = time.time() - (jobs._JOB_TTL_SECONDS + 10)
    # creating another job triggers a prune
    await jobs.create_job()
    assert jobs.get_job(job.id) is None
