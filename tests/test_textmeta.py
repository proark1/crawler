from __future__ import annotations

from app import textmeta


def test_reading_stats_empty():
    assert textmeta.reading_stats("") == (0, 0)
    assert textmeta.reading_stats(None) == (0, 0)


def test_reading_stats_counts_words_and_minutes():
    words, minutes = textmeta.reading_stats("word " * 400)
    assert words == 400
    assert minutes == 2  # 400 / 200 wpm


def test_reading_stats_short_text_is_at_least_one_minute():
    words, minutes = textmeta.reading_stats("a few words here")
    assert words == 4
    assert minutes == 1


def test_detect_language_none_when_unavailable_or_short():
    # Returns None for too-short text regardless of whether py3langid is present.
    assert textmeta.detect_language("hi") is None
    assert textmeta.detect_language(None) is None


def test_language_available_is_bool():
    assert isinstance(textmeta.language_available(), bool)
