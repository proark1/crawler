from __future__ import annotations

from app import pdfextract


def test_extract_text_none_on_empty():
    assert pdfextract.extract_text(b"") is None


def test_extract_text_none_on_garbage():
    # Not a valid PDF -> None (also covers the pypdf-not-installed case).
    assert pdfextract.extract_text(b"%PDF-1.4 not really a pdf") is None


def test_available_is_bool():
    assert isinstance(pdfextract.available(), bool)
