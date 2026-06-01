"""Structured JSON logging and a tiny in-process metrics registry.

Kept dependency-free: logs are emitted as one JSON object per line (friendly to
Railway / Loki / Datadog) and metrics are exposed at /metrics in Prometheus
text format without pulling in a client library.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from threading import Lock

from .config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    # Quiet noisy access logs; we emit our own request metrics.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self._lock = Lock()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] += value

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            items = list(self._counters.items())
        for (name, labels), value in sorted(items):
            if labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f"{name}{{{label_str}}} {value}")
            else:
                lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
