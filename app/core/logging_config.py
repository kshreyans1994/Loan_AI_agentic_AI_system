"""
Central logging setup.

One place to configure how every log line in this project looks, so a
developer debugging a request doesn't have to guess which module set
up its own handler with its own format. Call `configure_logging()`
once at process startup (`app/main.py` does this); everywhere else,
just `logging.getLogger(__name__)` as normal — nothing else needs to
import from this module.

Two output formats, picked via `Settings.log_format`:

- "text" (default, best for local dev): human-readable single line per
  record, e.g.
    2026-08-02 10:14:03 INFO  app.agents.decision_agent [session=abc123] risk_score=0.92 requires_human_review=True (dur=4ms)
- "json" (best for shipping to a log aggregator in a real deployment):
  one JSON object per line, machine-parseable, same fields.

Every log call in this codebase that's inside a graph node should
include `session_id=` (and `extra={"session_id": ...}` if using the
adapter below) so a developer can grep/filter one conversation's full
trace out of a shared log stream — session_id is the correlation ID
this whole pipeline is keyed on already (LangGraph thread_id, DB rows,
audit log), so reusing it here instead of inventing a separate
request/trace ID keeps one turn traceable end-to-end with one grep.
"""
from __future__ import annotations

import json
import logging
import sys
import time

from app.core.config import get_settings


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # session_id (and anything else passed via extra=) rides along
        # on the record as a plain attribute — surface it if present.
        for key in ("session_id", "node", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        session_id = getattr(record, "session_id", None)
        prefix = f"[session={session_id}] " if session_id else ""
        node = getattr(record, "node", None)
        node_part = f"({node}) " if node else ""
        duration = getattr(record, "duration_ms", None)
        duration_part = f" (dur={duration}ms)" if duration is not None else ""
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<7} {record.name} {node_part}{prefix}{record.getMessage()}{duration_part}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


def configure_logging() -> None:
    """Idempotent — safe to call more than once (e.g. once from
    app/main.py at import time, and again in a test fixture) without
    duplicating handlers."""
    global _configured
    if _configured:
        return

    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if settings.log_format == "json" else _TextFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # Groq/LangChain's own HTTP client logging is noisy at INFO and
    # rarely what a developer debugging THIS pipeline wants to see —
    # tone it down independently of the app's own log level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _configured = True


def log_with_session(logger: logging.Logger, level: int, session_id: str | None, message: str, **fields) -> None:
    """Thin wrapper so call sites don't have to remember the `extra={...}`
    dict shape every time. Any keyword becomes a field on the record —
    formatters above surface session_id/node/duration_ms specifically,
    everything else just doesn't print in text mode (still present in
    json mode) unless a formatter is extended to include it."""
    logger.log(level, message, extra={"session_id": session_id, **fields})
