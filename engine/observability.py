"""Logging, request correlation, and error tracking.

- Every request gets an X-Request-ID (accepted from the proxy or generated),
  carried in a contextvar so every log line emitted while handling it —
  including from services — is correlated.
- LOG_FORMAT=json (default in production) emits one JSON object per line so
  the platform's log search can filter on level/logger/request_id.
- SENTRY_DSN enables error tracking when the optional sentry-sdk is
  installed; absence of either is not an error.
"""
import contextvars
import json
import logging
import uuid

from engine.config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if settings.resolved_log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
        ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


def init_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; "
            "error tracking disabled"
        )
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
