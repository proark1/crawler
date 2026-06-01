"""HTML -> (title, text, markdown, links, metadata) extraction.

These calls are CPU-bound (lxml / selectolax / trafilatura). They are invoked
via ``asyncio.to_thread`` from the crawler so they never block the event loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin

import trafilatura
from selectolax.parser import HTMLParser

from .urls import normalize


@dataclass
class Extracted:
    title: str | None = None
    text: str | None = None
    markdown: str | None = None
    links: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _clean(value: str | None) -> str | None:
    """Strip NUL bytes that Postgres TEXT columns reject."""
    if value is None:
        return None
    return value.replace("\x00", "")


def extract(html: str, url: str) -> Extracted:
    out = Extracted()

    try:
        tree = HTMLParser(html)
        node = tree.css_first("title")
        if node:
            out.title = node.text(strip=True) or None

        # Description / canonical for nicer metadata.
        for meta in tree.css("meta[name='description'], meta[property='og:description']"):
            content = meta.attributes.get("content")
            if content:
                out.metadata.setdefault("description", content.strip())
                break

        seen: set[str] = set()
        for a in tree.css("a[href]"):
            href = a.attributes.get("href")
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            absolute = normalize(urljoin(url, href))
            if absolute.startswith(("http://", "https://")) and absolute not in seen:
                seen.add(absolute)
                out.links.append(absolute)
    except Exception as exc:  # noqa: BLE001
        out.metadata["parse_error"] = str(exc)

    out.text = _clean(
        trafilatura.extract(
            html, url=url, include_comments=False, include_tables=True, favor_recall=True
        )
    )
    out.markdown = _clean(
        trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            output_format="markdown",
            include_links=True,
        )
    )
    if not out.title:
        out.title = None
    return out


def looks_empty(text: str | None) -> bool:
    return not text or len(text.strip()) < 200
