from __future__ import annotations

import pytest

from app import concurrency
from app.config import settings


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings, "adaptive_concurrency", True)
    monkeypatch.setattr(settings, "host_concurrency_start", 2)
    monkeypatch.setattr(settings, "host_concurrency_max", 8)
    monkeypatch.setattr(settings, "circuit_breaker_threshold", 3)
    monkeypatch.setattr(settings, "circuit_cooldown", 100.0)


@pytest.mark.asyncio
async def test_slot_acquires_and_releases():
    lim = concurrency.HostLimiter()
    async with lim.slot("x.com"):
        st = lim._state("x.com")
        assert st.active == 1
    assert lim._state("x.com").active == 0


def test_aimd_increase_and_decrease():
    lim = concurrency.HostLimiter()
    lim.record_success("x.com")
    assert lim._state("x.com").limit == 2.5  # additive increase
    lim.record_block("x.com")
    assert lim._state("x.com").limit == 1.25  # multiplicative decrease


def test_circuit_breaker_trips_after_threshold():
    lim = concurrency.HostLimiter()
    for _ in range(3):  # threshold
        lim.record_block("y.com")
    with pytest.raises(concurrency.CircuitOpen):
        lim.check_circuit("y.com")
    # A success clears the breaker.
    lim.record_success("y.com")
    lim.check_circuit("y.com")  # no raise


@pytest.mark.asyncio
async def test_slot_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "adaptive_concurrency", False)
    lim = concurrency.HostLimiter()
    async with lim.slot("z.com"):
        pass
    # No state created, circuit checks are inert.
    lim.check_circuit("z.com")
