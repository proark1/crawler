"""In-process async crawl jobs with a pub/sub event bus for SSE streaming.

A job runs a ``crawl_site`` in a background task, persisting each page as it
completes and publishing an event so connected clients see live progress.
State is also written to Postgres so a client that (re)connects after the fact
can still read the final result. Designed for a single app instance (Railway);
swap the registry for Redis to scale horizontally.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import db
from .crawler import crawl_one, crawl_site

log = logging.getLogger("crawler.jobs")


class _Channel:
    """Fan-out of job events to live SSE subscribers, with terminal latch."""

    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()
        self.done = asyncio.Event()
        self.count = 0

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self.subscribers):
            q.put_nowait(event)

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)


_channels: dict[int, _Channel] = {}
_tasks: set[asyncio.Task] = set()


def _strip_html(page: dict) -> dict:
    page = dict(page)
    page.pop("html", None)
    return page


async def start(params: dict[str, Any]) -> int:
    job_id = await db.create_job(params)
    channel = _Channel()
    _channels[job_id] = channel
    task = asyncio.create_task(_run(job_id, params, channel))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_id


async def _run(job_id: int, params: dict[str, Any], channel: _Channel) -> None:
    async def on_page(res: dict) -> None:
        try:
            saved = await db.add_job_page(job_id, res)
        except Exception as exc:  # noqa: BLE001 - persistence failure shouldn't kill the crawl
            log.warning("job %s: failed to persist page %s: %s", job_id, res.get("url"), exc)
            saved = res
        channel.count += 1
        channel.publish({"type": "page", "page": _strip_html(saved), "count": channel.count})

    try:
        if params.get("follow_links"):
            await crawl_site(
                params["url"],
                render=params.get("render", "auto"),
                max_depth=params.get("max_depth", 1),
                max_pages=params.get("max_pages", 10),
                same_host_only=params.get("same_host_only", True),
                on_page=on_page,
            )
        else:
            res = await crawl_one(params["url"], render=params.get("render", "auto"),
                                  check_robots=True)
            await on_page(res)
        await db.update_job(job_id, status="done", total=channel.count)
        channel.publish({"type": "done", "status": "done", "total": channel.count})
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        await db.update_job(job_id, status="failed", total=channel.count, error=str(exc))
        channel.publish({"type": "done", "status": "failed", "error": str(exc),
                         "total": channel.count})
    finally:
        channel.done.set()


def get_channel(job_id: int) -> _Channel | None:
    return _channels.get(job_id)


async def shutdown() -> None:
    for task in list(_tasks):
        task.cancel()
    for task in list(_tasks):
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
