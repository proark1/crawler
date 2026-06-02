"""Tiny bounded-size and TTL caches (no external deps).

Used to cap the per-host bookkeeping maps in the crawler (politeness locks,
cookie jars, robots parsers) so a long-running, high-cardinality crawl can't
leak memory indefinitely.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class BoundedLRU(Generic[K, V]):
    """LRU dict that evicts the least-recently-used entries past ``maxsize``."""

    def __init__(self, maxsize: int) -> None:
        self._max = max(1, maxsize)
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def __contains__(self, key: K) -> bool:
        return key in self._data

    def set(self, key: K, value: V) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def setdefault(self, key: K, default: V) -> V:
        # Test membership (not `get() is not None`) so a legitimately-stored
        # falsy/None value isn't mistaken for "absent" and overwritten.
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        self.set(key, default)
        return default

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


class TTLCache(Generic[K, V]):
    """Bounded cache whose entries expire after ``ttl`` seconds."""

    def __init__(self, maxsize: int, ttl: float) -> None:
        self._ttl = ttl
        self._lru: BoundedLRU[K, tuple[float, V]] = BoundedLRU(maxsize)

    def get(self, key: K) -> V | None:
        entry = self._lru.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            return None
        return value

    def set(self, key: K, value: V) -> None:
        self._lru.set(key, (time.monotonic() + self._ttl, value))

    def clear(self) -> None:
        self._lru.clear()
