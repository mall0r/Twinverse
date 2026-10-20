"""Retention for per-run instance and helper logs."""

import re
import time
from pathlib import Path

from .paths import LogPaths

_INSTANCE_RE = re.compile(r"^instance-(\d+)-")
_HELPER_RE = re.compile(r"^overlay-focus-")


def _prune(directory: Path, pattern: re.Pattern[str], keep: int, max_age_days: int) -> int:
    if not directory.is_dir():
        return 0
    groups: dict[str, list[Path]] = {}
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        match = pattern.match(path.name)
        if match:
            groups.setdefault(match.group(1) if match.groups() else "all", []).append(path)

    removed = 0
    cutoff = time.time() - max_age_days * 86400
    for paths in groups.values():
        paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for index, path in enumerate(paths):
            try:
                too_old = path.stat().st_mtime < cutoff
                if index < keep and not too_old:
                    continue
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def prune_logs(paths: LogPaths, keep_instances: int = 5, keep_helpers: int = 2, max_age_days: int = 14) -> int:
    """Remove old run logs while keeping the newest files of each instance."""
    removed = _prune(paths.instances, _INSTANCE_RE, keep_instances, max_age_days)
    removed += _prune(paths.helpers, _HELPER_RE, keep_helpers, max_age_days)
    return removed
