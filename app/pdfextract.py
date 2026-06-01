"""PDF text extraction.

Optional: requires the `[pdf]` extra (pypdf). When pypdf isn't installed, or the
PDF can't be parsed, extraction returns None and the crawler records the page as
a skipped non-HTML body — same as before.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger("crawler.pdf")

try:  # pragma: no cover - import probe
    import pypdf

    _PYPDF = True
except BaseException:  # noqa: BLE001 -- a broken optional dep must never crash import
    pypdf = None  # type: ignore[assignment]
    _PYPDF = False


def available() -> bool:
    return _PYPDF


def extract_text(data: bytes, max_pages: int = 100) -> str | None:
    """Return the concatenated text of a PDF, or None if it can't be parsed."""
    if not _PYPDF or not data:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages[:max_pages]:
            try:
                txt = page.extract_text() or ""
            except Exception:  # noqa: BLE001 -- skip unreadable pages
                txt = ""
            if txt.strip():
                parts.append(txt.strip())
        text = "\n\n".join(parts).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        log.debug("pdf extraction failed: %s", exc)
        return None
