"""Shared logging configuration including API key redaction, JSON structured logging, and task_id context propagation."""

import contextvars
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime

# Tight key patterns: real Anthropic keys (sk-ant-...) and other long API keys (sk-... with 32+ chars).
# Short false positives like "sk-0" are not redacted.
_KEY_ANTHROPIC = re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}", re.IGNORECASE)
_KEY_GENERIC = re.compile(r"sk-[a-zA-Z0-9_-]{32,}", re.IGNORECASE)


def _redact_keys_in_text(text: str) -> str:
    """Redact API keys from a string."""
    text = _KEY_ANTHROPIC.sub("***", text)
    text = _KEY_GENERIC.sub("***", text)
    return text


_redacting_installed = False

# ── Task ID context propagation ──────────────────────────────────────────

_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)


def set_task_id(task_id: str | None) -> None:
    """Set the current task_id in the async/thread-local context."""
    _task_id_var.set(task_id)


def get_task_id() -> str | None:
    """Get the current task_id from the async/thread-local context."""
    return _task_id_var.get()


class TaskIdFilter(logging.Filter):
    """Handler-level filter that injects task_id from context on records that don't already have one.

    This ensures plain loggers (e.g., pipeline.py) that don't use TaskContextAdapter
    still get task_id injected automatically.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "task_id") or record.task_id is None:
            tid = get_task_id()
            record.task_id = tid
        return True


class TaskContextAdapter(logging.LoggerAdapter):
    """LoggerAdapter that injects task_id into every log record."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        if "task_id" not in extra:
            task_id = get_task_id()
            extra["task_id"] = task_id
            kwargs["extra"] = extra
        return msg, kwargs


# ── JSON structured formatter ────────────────────────────────────────────


def _iso_timestamp() -> str:
    """Return current UTC timestamp with milliseconds."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(UTC).microsecond // 1000:03d}"
    )


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line with standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "ts": _iso_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "event": str(record.msg),
        }

        # Always include task_id (null when outside request context)
        task_id = getattr(record, "task_id", None)
        log_entry["task_id"] = task_id

        # Include redacted exception info when present
        if record.exc_info and record.exc_info[0]:
            exc_text = self.formatException(record.exc_info)
            log_entry["exception"] = _redact_keys_in_text(exc_text)

        # Format message with args
        if record.args:
            try:
                log_entry["event"] = str(record.msg) % record.args
            except Exception:
                log_entry["event"] = str(record.msg)

        # Include any extra fields (redacted)
        standard_attrs = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "task_id",
        }

        def _redact_extra(value):
            if isinstance(value, str):
                return _redact_keys_in_text(value)
            if isinstance(value, dict):
                return {_redact_keys_in_text(k): _redact_extra(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_redact_extra(v) for v in value]
            return value

        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                redacted = _redact_extra(value)
                try:
                    json.dumps(redacted)
                    log_entry[key] = redacted
                except (TypeError, ValueError):
                    log_entry[key] = str(redacted)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ── Colored console formatter (development) ──────────────────────────────


class ColoredFormatter(logging.Formatter):
    """Human-readable colored output for terminal use."""

    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"
    GRAY = "\033[90m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        task_id = getattr(record, "task_id", None)

        # Format message with args
        msg = str(record.msg)
        if record.args:
            try:
                msg = str(record.msg) % record.args
            except Exception:
                pass

        parts = [
            f"{self.GRAY}{ts}{self.RESET}",
            f"{color}{record.levelname:<7}{self.RESET}",
        ]
        if task_id:
            parts.append(f"{self.GRAY}[{task_id[:8]}]{self.RESET}")
        parts.append(msg)

        return " ".join(parts)


# ── Setup ────────────────────────────────────────────────────────────────


def setup_json_logging() -> None:
    """Install structured logging based on LOG_FORMAT environment variable.

    - ``LOG_FORMAT=json`` (or unset in Docker): JSON lines to stdout.
    - ``LOG_FORMAT=text`` (or unset without Docker): colorized text to stdout.
    - Unrecognized value: falls back to JSON with a warning.
    """
    from app.config import settings

    log_format = settings.log_format
    in_docker = os.path.exists("/.dockerenv")

    if not log_format:
        log_format = "json" if in_docker else "text"

    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(TaskIdFilter())

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    elif log_format == "text":
        handler.setFormatter(ColoredFormatter())
    else:
        handler.setFormatter(JsonFormatter())

    root.addHandler(handler)
    root.setLevel(logging.INFO)

    if log_format not in ("json", "text"):
        root.warning("Unrecognized LOG_FORMAT=%r, falling back to JSON", log_format)


# ── API key redaction (preserved from original, tightened patterns) ──────


def _redact_value(v):
    """Redact keys in a string value, pass through non-strings."""
    if isinstance(v, str):
        return _redact_keys_in_text(v)
    return v


def _make_redacting_factory(old_factory):
    def redacting_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        if record.msg and isinstance(record.msg, str):
            record.msg = _redact_keys_in_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_value(v) for k, v in record.args.items()}
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(_redact_value(a) for a in record.args)
        return record

    return redacting_factory


def install_log_filter():
    """Install process-wide API key redaction via LogRecordFactory (idempotent)."""
    global _redacting_installed
    if _redacting_installed:
        return
    _redacting_installed = True

    old_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(_make_redacting_factory(old_factory))
