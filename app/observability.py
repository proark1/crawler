"""Structured logging, optional Sentry, and Prometheus metrics.

All three degrade gracefully: if the optional library isn't installed (or the
feature is disabled in settings) the helpers become no-ops so the service still
runs with a minimal dependency set.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from .config import settings

try:  # optional dependency
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _PROM = True
except Exception:  # noqa: BLE001
    _PROM = False
    CONTENT_TYPE_LATEST = "text/plain"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0)
        logging.getLogger("crawler").info("sentry initialised")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("crawler").warning("sentry init failed: %s", exc)


if _PROM and settings.enable_metrics:
    CRAWL_PAGES = Counter(
        "crawler_pages_total", "Pages crawled", ["render_mode", "outcome"]
    )
    CRAWL_DURATION = Histogram("crawler_crawl_seconds", "Crawl request duration seconds")
    HTTP_REQUESTS = Counter(
        "crawler_http_requests_total", "API requests", ["method", "path", "status"]
    )
else:  # pragma: no cover - exercised only when prometheus is absent
    CRAWL_PAGES = CRAWL_DURATION = HTTP_REQUESTS = None


def record_pages(pages: list[dict]) -> None:
    if CRAWL_PAGES is None:
        return
    for p in pages:
        outcome = "error" if p.get("error") else "ok"
        CRAWL_PAGES.labels(render_mode=p.get("render_mode", "unknown"), outcome=outcome).inc()


def record_http(method: str, path: str, status: int) -> None:
    if HTTP_REQUESTS is None:
        return
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()


def metrics_enabled() -> bool:
    return _PROM and settings.enable_metrics


def render_metrics() -> tuple[bytes, str]:
    if not metrics_enabled():
        return b"", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
