"""Per-host politeness throttle: spaces out requests to the same origin."""
from __future__ import annotations

import asyncio
import time


class HostThrottle:
    def __init__(self, default_delay: float) -> None:
        self._default = default_delay
        self._next_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def wait(self, host: str, delay: float | None = None) -> None:
        """Block until it's polite to hit ``host`` again."""
        gap = self._default if delay is None else delay
        if gap <= 0:
            return
        async with self._lock(host):
            now = time.monotonic()
            earliest = self._next_at.get(host, 0.0)
            if now < earliest:
                await asyncio.sleep(earliest - now)
            self._next_at[host] = max(now, earliest) + gap
