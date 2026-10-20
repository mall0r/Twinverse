"""Filesystem layout for Twinverse logs."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.config import Config, ensure_private_dir


@dataclass(frozen=True)
class LogPaths:
    """Directories and stable files used by the logging subsystem."""

    root: Path

    @classmethod
    def resolve(cls, override: Optional[Path] = None) -> "LogPaths":
        """Return the log layout, honoring an explicit directory override."""
        if override is not None:
            root = Path(override).expanduser()
        else:
            root = Config.logs_dir()
        return cls(root=root)

    @property
    def main_log(self) -> Path:
        """Main application log, rotated by the file handler."""
        return self.root / "twinverse.log"

    @property
    def crash_log(self) -> Path:
        """Low-level crash output written by :mod:`faulthandler`."""
        return self.root / "crash.log"

    @property
    def instances(self) -> Path:
        """Directory holding one log per instance launch."""
        return self.root / "instances"

    @property
    def helpers(self) -> Path:
        """Directory holding logs from standalone helper processes."""
        return self.root / "helpers"

    def ensure(self) -> "LogPaths":
        """Create every directory and stable file with private permissions."""
        ensure_private_dir(self.root)
        ensure_private_dir(self.instances)
        ensure_private_dir(self.helpers)
        for path in (self.main_log, self.crash_log):
            if not path.exists():
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                os.close(descriptor)
            else:
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
        return self

    def as_dict(self) -> dict[str, str]:
        """Return the layout as strings for diagnostics."""
        return {
            "root": str(self.root),
            "main_log": str(self.main_log),
            "crash_log": str(self.crash_log),
            "instances": str(self.instances),
            "helpers": str(self.helpers),
        }
