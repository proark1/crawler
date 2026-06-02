"""Async crawl-job registry.

Jobs run as in-process asyncio tasks (fast path) and are mirrored to Postgres so
their terminal state survives restarts and is visible from other instances. On
completion an optional webhook is POSTed with the result. DB mirroring is
best-effort: if the database is unreachable the in-memory job still works.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from . import db, ssrf
from .config import settings

log = logging.getLogger("crawler.jobs")

JobStatus = Literal["pending", "running", "done", "error", "cancelled"]

_JOB_TTL_SECONDS = 60 * 60  # keep finished jobs in memory for an hour
_MAX_JOBS = 500


@dataclass
class Job:
    id: str
    status: JobStatus = "pending"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    progress: int = 0
    total: int | None = None
    pages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    webhook_url: str | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "count": len(self.pages),
            "pages": self.pages,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def _db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "request": self.request,
            "pages": self.pages,
            "error": self.error,
            "webhook_url": self.webhook_url,
        }


_jobs: dict[str, Job] = {}
_lock = asyncio.Lock()


def _prune() -> None:
    now = time.time()
    stale = [
        jid
        for jid, job in _jobs.items()
        if job.status in ("done", "error") and now - job.updated_at > _JOB_TTL_SECONDS
    ]
    for jid in stale:
        _jobs.pop(jid, None)
    if len(_jobs) > _MAX_JOBS:
        finished = sorted(
            (j for j in _jobs.values() if j.status in ("done", "error")),
            key=lambda j: j.updated_at,
        )
        for job in finished[: len(_jobs) - _MAX_JOBS]:
            _jobs.pop(job.id, None)


async def _persist(job: Job) -> None:
    """Best-effort mirror to Postgres; never let DB issues break the job."""
    try:
        await db.upsert_job(job._db_row())
    except Exception as exc:  # noqa: BLE001
        log.debug("job persist skipped: %s", exc)


async def create_job(
    request: dict[str, Any] | None = None, webhook_url: str | None = None
) -> Job:
    async with _lock:
        _prune()
        job = Job(id=uuid.uuid4().hex, request=request or {}, webhook_url=webhook_url)
        _jobs[job.id] = job
    await _persist(job)
    return job


async def mark(job: Job, **changes: Any) -> None:
    for key, value in changes.items():
        setattr(job, key, value)
    job.updated_at = time.time()
    await _persist(job)


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


async def load_public(job_id: str) -> dict[str, Any] | None:
    """In-memory job if present, otherwise the persisted snapshot."""
    job = _jobs.get(job_id)
    if job is not None:
        return job.public()
    try:
        row = await db.get_job_row(job_id)
    except Exception:  # noqa: BLE001
        return None
    if row is None:
        return None
    pages = row.get("pages") or []
    return {
        "id": row["id"],
        "status": row["status"],
        "progress": row.get("progress", 0),
        "total": row.get("total"),
        "count": len(pages),
        "pages": pages,
        "error": row.get("error"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def fire_webhook(job: Job) -> None:
    """Deliver the job result to its webhook, optionally HMAC-signed, with retries.

    Signing lets the receiver verify authenticity (X-Crawler-Signature is the
    hex HMAC-SHA256 of the raw body using ``webhook_secret``). Delivery is retried
    with exponential backoff so a brief receiver outage doesn't drop the event.
    """
    if not job.webhook_url:
        return
    # Re-validate at delivery time (defence in depth): the URL was checked on
    # submit, but DNS can change, and this guards jobs restored from the DB that
    # never went through the submit-time check.
    try:
        await ssrf.assert_url_allowed(job.webhook_url)
    except ssrf.BlockedAddressError as exc:
        log.warning("webhook for job %s refused (SSRF): %s", job.id, exc)
        return
    body = json.dumps(job.public(), default=str).encode()
    headers = {"Content-Type": "application/json"}
    if settings.webhook_secret:
        sig = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Crawler-Signature"] = f"sha256={sig}"

    attempts = max(1, settings.webhook_retries)
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.post(job.webhook_url, content=body, headers=headers)
            if resp.status_code < 500:
                return  # delivered (2xx/3xx/4xx are all "the receiver got it")
            raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
        except Exception as exc:  # noqa: BLE001
            if attempt + 1 >= attempts:
                log.warning(
                    "webhook delivery failed for job %s after %d attempts: %s",
                    job.id, attempts, exc,
                )
                return
            await asyncio.sleep(min(30.0, 2.0**attempt))


async def cancel(job_id: str) -> bool:
    """Cancel a running job. Returns False if unknown or already finished."""
    job = _jobs.get(job_id)
    if job is None or job.status in ("done", "error", "cancelled"):
        return False
    if job._task is not None and not job._task.done():
        job._task.cancel()
    await mark(job, status="cancelled", error="cancelled by request")
    return True


async def cancel_all() -> None:
    """Cancel any in-flight job tasks on shutdown."""
    for job in list(_jobs.values()):
        if job._task is not None and not job._task.done():
            job._task.cancel()
