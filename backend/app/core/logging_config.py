"""
Structured JSON logging for the CRM backend.

All financial mutations and slow-query warnings use this module so logs are
machine-parseable in Render / Datadog / any log aggregator.

Usage
-----
    from app.core.logging_config import get_logger, log_event

    logger = get_logger(__name__)
    log_event("expense_created", amount=500, performed_by=user_id)
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit every log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Attach any extra keys passed via extra={} or record.__dict__
        for key, val in record.__dict__.items():
            if key not in (
                "args", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "message",
                "module", "msecs", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread",
                "threadName",
            ):
                payload[key] = val
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Call once at app startup to switch all handlers to JSON format."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ── Convenience event emitter ─────────────────────────────────────────────────
_event_logger = logging.getLogger("crm.events")


def log_event(event: str, **kwargs: Any) -> None:
    """Emit a structured INFO log for a named event with arbitrary fields."""
    _event_logger.info(
        event,
        extra={
            "event": event,
            "ts_epoch": time.time(),
            **kwargs,
        },
    )


# ── Metrics accumulator (in-process, Prometheus-ready later) ──────────────────
_metrics: dict[str, list[float]] = {}


def record_latency(metric_name: str, elapsed_ms: float) -> None:
    bucket = _metrics.setdefault(metric_name, [])
    bucket.append(elapsed_ms)
    if len(bucket) > 1000:
        _metrics[metric_name] = bucket[-500:]   # keep last 500 samples


def get_metrics_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name, samples in _metrics.items():
        if not samples:
            continue
        summary[name] = {
            "count": len(samples),
            "avg_ms": round(sum(samples) / len(samples), 2),
            "min_ms": round(min(samples), 2),
            "max_ms": round(max(samples), 2),
            "p95_ms": round(sorted(samples)[int(len(samples) * 0.95)], 2),
        }
    return summary
