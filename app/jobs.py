"""In-process async job registry for long-running crawls.

Suitable for the single-instance deployment this service targets. A crawl of
many pages can take minutes; rather than holding an HTTP connection open the
whole time, callers submit a job, get an id back immediately, and poll for
status. Jobs live in memory and are pruned after a TTL.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["pending", "running", "done", "error"]

_JOB_TTL_SECONDS = 60 * 60  # keep finished jobs around for an hour
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
    # Hard cap to bound memory: drop oldest finished jobs first.
    if len(_jobs) > _MAX_JOBS:
        finished = sorted(
            (j for j in _jobs.values() if j.status in ("done", "error")),
            key=lambda j: j.updated_at,
        )
        for job in finished[: len(_jobs) - _MAX_JOBS]:
            _jobs.pop(job.id, None)


async def create_job() -> Job:
    async with _lock:
        _prune()
        job = Job(id=uuid.uuid4().hex)
        _jobs[job.id] = job
        return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


async def cancel_all() -> None:
    """Cancel any in-flight job tasks on shutdown."""
    for job in list(_jobs.values()):
        if job._task is not None and not job._task.done():
            job._task.cancel()
