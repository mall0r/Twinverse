"""Handlers with private permissions and failure-safe console output."""

import logging
import logging.handlers
import os
import sys


class PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file handler that creates logs with mode ``0600``."""

    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.baseFilename, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        except OSError:
            pass
        return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)

    def handleError(self, record: logging.LogRecord) -> None:
        """Report a file sink failure once per process without recursive logging."""
        try:
            sys.stderr.write(f"Twinverse: could not write to {self.baseFilename}\n")
        except Exception:
            pass


class SafeStderrHandler(logging.StreamHandler):
    """Stream handler that never lets a broken stderr stop the application."""

    def handleError(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write("Twinverse: could not write logs to stderr\n")
        except Exception:
            pass
