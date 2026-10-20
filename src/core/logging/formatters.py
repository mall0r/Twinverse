"""Text and JSON formatters used by Twinverse logs."""

import json
import logging
from datetime import datetime
from typing import Any

from .redaction import redact_mapping, redact_text

_STANDARD_FIELDS = {
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
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
    "context",
    "context_fields",
    "run_id",
}


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")


class TextFormatter(logging.Formatter):
    """Human-readable single-line log records."""

    def __init__(self) -> None:
        """Build the format of a text record."""
        super().__init__("%(asctime)s %(levelname)-8s %(name)s [%(context)s] %(message)s")

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Return the time of the record with the timezone of the machine."""
        return _timestamp(record)

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a masked line of text."""
        if not hasattr(record, "context"):
            record.context = getattr(record, "run_id", "unconfigured")
        return redact_text(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line, suitable for automated diagnosis."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as one masked JSON object."""
        payload: dict[str, Any] = {
            "timestamp": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "run_id": getattr(record, "run_id", None),
            "thread": record.threadName,
            "process": record.process,
        }

        context = getattr(record, "context_fields", {})
        if isinstance(context, dict):
            for key, value in redact_mapping(context).items():
                payload.setdefault(str(key), value)

        for key, value in record.__dict__.items():
            if key in _STANDARD_FIELDS or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[str(key)] = _json_safe(value)

        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = redact_text(self.formatStack(record.stack_info))

        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in redact_mapping(value).items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return redact_text(value)
