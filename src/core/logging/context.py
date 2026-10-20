"""Contextual fields attached to every log record."""

import contextvars
from contextlib import contextmanager
from typing import Iterator, Mapping, Optional

# The run identifier belongs to the process, not to a context: a launch runs in
# a worker thread and a ``ContextVar`` set in the main thread is invisible
# there, which would leave every record of the launch without its run id.
_run_id: Optional[str] = None

# The contextual fields describe what a thread is doing right now, so they
# follow the context of the thread that emits the record.
_FIELDS: contextvars.ContextVar[Optional[Mapping[str, object]]] = contextvars.ContextVar(
    "twinverse_log_fields", default=None
)


def set_run_id(run_id: Optional[str]) -> Optional[str]:
    """Set the run identifier of the process and return the previous one."""
    global _run_id
    previous = _run_id
    _run_id = run_id
    return previous


def current_run_id(default: str = "unconfigured") -> str:
    """Return the run identifier, or a readable fallback."""
    return _run_id or default


def current_fields() -> dict[str, object]:
    """Return a copy of the contextual fields of the current context."""
    return dict(_FIELDS.get() or {})


@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    """Add fields to logs emitted inside the block.

    A value of ``None`` removes an inherited field instead of rendering the
    text ``None``. Nested contexts inherit and override fields.
    """
    current = dict(_FIELDS.get() or {})
    for key, value in fields.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    token = _FIELDS.set(current)
    try:
        yield
    finally:
        _FIELDS.reset(token)
