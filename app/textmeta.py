"""Lightweight text metadata: word count, reading time, and language detection.

Word count / reading time are pure-stdlib and always computed. Language
detection is best-effort and optional (the `[lang]` extra installs py3langid, a
pure-Python detector); when it isn't installed, detection is simply skipped.
"""
from __future__ import annotations

_WORDS_PER_MINUTE = 200

try:  # pragma: no cover - import probe
    import py3langid as _langid

    _LANGID = True
except Exception:  # noqa: BLE001
    _langid = None  # type: ignore[assignment]
    _LANGID = False


def reading_stats(text: str | None) -> tuple[int, int]:
    """Return (word_count, reading_time_minutes) for the given text."""
    if not text:
        return 0, 0
    words = len(text.split())
    minutes = max(1, round(words / _WORDS_PER_MINUTE)) if words else 0
    return words, minutes


def language_available() -> bool:
    return _LANGID


def detect_language(text: str | None) -> str | None:
    """Best-effort ISO-639-1 language code for text, or None."""
    if not _LANGID or not text:
        return None
    sample = text.strip()[:2000]
    if len(sample) < 20:  # too short to be reliable
        return None
    try:
        lang, _conf = _langid.classify(sample)
        return lang
    except Exception:  # noqa: BLE001
        return None
