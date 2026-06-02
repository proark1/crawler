import time

from app.lrucache import BoundedLRU, TTLCache


def test_bounded_lru_evicts_oldest():
    c: BoundedLRU[str, int] = BoundedLRU(2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # evicts "a"
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert len(c) == 2


def test_bounded_lru_get_refreshes_recency():
    c: BoundedLRU[str, int] = BoundedLRU(2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # "a" now most-recently-used
    c.set("c", 3)  # should evict "b", not "a"
    assert c.get("a") == 1
    assert c.get("b") is None


def test_bounded_lru_setdefault():
    c: BoundedLRU[str, int] = BoundedLRU(4)
    assert c.setdefault("x", 5) == 5
    assert c.setdefault("x", 9) == 5  # existing value kept


def test_bounded_lru_setdefault_keeps_stored_falsy_value():
    # A legitimately-stored falsy value (0/None/False) must not be mistaken for
    # "absent" and overwritten by setdefault.
    c: BoundedLRU[str, int] = BoundedLRU(4)
    assert c.setdefault("z", 0) == 0
    assert c.setdefault("z", 7) == 0  # 0 is present, kept
    assert c.get("z") == 0


def test_ttl_cache_expires(monkeypatch):
    c: TTLCache[str, str] = TTLCache(10, ttl=100.0)
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    c.set("k", "v")
    assert c.get("k") == "v"
    now[0] += 101.0
    assert c.get("k") is None  # expired


def test_ttl_cache_distinguishes_stored_none_via_sentinel():
    # Storing a falsy-but-present marker round-trips (used for robots "allow").
    c: TTLCache[str, object] = TTLCache(10, ttl=100.0)
    c.set("host", False)
    assert c.get("host") is False
    assert c.get("missing") is None
