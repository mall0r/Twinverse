"""Filters that keep logs contextual and third-party noise low."""

import logging
from typing import Any

from .context import current_fields, current_run_id


class ContextFilter(logging.Filter):
    """Attach the run id and the current context fields to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach the context to the record and let it through."""
        run_id = getattr(record, "run_id", None) or current_run_id()
        record.run_id = run_id

        fields: dict[str, Any] = {}
        for key, value in current_fields().items():
            if not hasattr(record, key):
                setattr(record, key, value)
            fields[key] = getattr(record, key)
        if run_id:
            fields.setdefault("run_id", run_id)

        # A caller can pass ``extra={"instance": 1}`` without a context.
        for key in ("instance", "phase"):
            if hasattr(record, key):
                fields[key] = getattr(record, key)

        record.context_fields = fields
        record.context = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        return True


class NamespaceFilter(logging.Filter):
    """Let Twinverse log at every level and third-party code only at warnings."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Let the records of the application through, and only warnings of others."""
        return record.name == "src" or record.name.startswith("src.") or record.levelno >= logging.WARNING
