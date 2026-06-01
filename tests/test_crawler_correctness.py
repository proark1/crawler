"""Block-detection guards added for correctness (no network needed)."""
from app import crawler
from app.config import settings


def test_404_is_not_treated_as_block(monkeypatch):
    monkeypatch.setattr(settings, "antibot_enabled", True)
    # A body that *does* match a vendor signature must still not count as a
    # block on a 404/410 "not found" response.
    blocky = "<html>... _incapsula_resource ...</html>"
    assert crawler._is_block(200, {}, blocky) is True  # sanity: signature works
    assert crawler._is_block(404, {}, blocky) is False
    assert crawler._is_block(410, {}, blocky) is False


def test_generic_status_block_still_detected(monkeypatch):
    monkeypatch.setattr(settings, "antibot_enabled", True)
    assert crawler._is_block(403, {}, None) is True
    assert crawler._is_block(429, {}, None) is True
    assert crawler._is_block(404, {}, None) is False


def test_block_detection_off_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "antibot_enabled", False)
    assert crawler._is_block(403, {}, None) is False
