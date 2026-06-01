"""Per-host adaptive concurrency (AIMD) and circuit breaking.

- `HostLimiter` gates concurrent requests per host with a dynamically sized
  semaphore: additive-increase on success, multiplicative-decrease on a block /
  429, so we push throughput on healthy hosts and back off on protected ones.
- `CircuitBreaker` short-circuits a host after repeated blocks for a cooldown,
  so we stop hammering (and getting IP-reputation-damaged by) a host that is
  consistently rejecting us.

State is per-process and bounded; both are no-ops when disabled in settings.
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from .config import settings


class CircuitOpen(Exception):
    """Raised when a host's breaker is open (cooling down)."""


class _HostState:
    __slots__ = ("limit", "active", "cond", "consecutive_blocks", "open_until")

    def __init__(self, start: int) -> None:
        self.limit = float(start)
        self.active = 0
        self.cond = asyncio.Condition()
        self.consecutive_blocks = 0
        self.open_until = 0.0


class HostLimiter:
    def __init__(self) -> None:
        self._hosts: OrderedDict[str, _HostState] = OrderedDict()

    def _state(self, host: str) -> _HostState:
        st = self._hosts.get(host)
        if st is None:
            st = _HostState(settings.host_concurrency_start)
            self._hosts[host] = st
            if len(self._hosts) > 10_000:
                self._hosts.popitem(last=False)
        self._hosts.move_to_end(host)
        return st

    def check_circuit(self, host: str) -> None:
        st = self._hosts.get(host)
        if st and st.open_until and time.monotonic() < st.open_until:
            raise CircuitOpen(host)

    @asynccontextmanager
    async def slot(self, host: str):
        """Acquire a concurrency slot for the host (no-op when disabled)."""
        if not settings.adaptive_concurrency:
            yield
            return
        self.check_circuit(host)
        st = self._state(host)
        async with st.cond:
            while st.active >= int(st.limit):
                await st.cond.wait()
            st.active += 1
        try:
            yield
        finally:
            async with st.cond:
                st.active -= 1
                st.cond.notify(1)

    def record_success(self, host: str) -> None:
        if not settings.adaptive_concurrency:
            return
        st = self._state(host)
        st.consecutive_blocks = 0
        st.open_until = 0.0
        # Additive increase, capped.
        st.limit = min(float(settings.host_concurrency_max), st.limit + 0.5)

    def record_block(self, host: str) -> None:
        if not settings.adaptive_concurrency:
            return
        st = self._state(host)
        st.consecutive_blocks += 1
        # Multiplicative decrease, floor of 1.
        st.limit = max(1.0, st.limit / 2)
        if st.consecutive_blocks >= settings.circuit_breaker_threshold:
            st.open_until = time.monotonic() + settings.circuit_cooldown


limiter = HostLimiter()
