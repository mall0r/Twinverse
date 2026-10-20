"""Retention, size limits and manual cleaning for the log files."""

import re
import shutil
import time
from pathlib import Path
from typing import Optional

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


def _log_files(paths: LogPaths) -> list[Path]:
    """Return every log file of the directory, oldest first."""
    files = []
    for directory in (paths.root, paths.instances, paths.helpers):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            files.append(path)
    files.sort(key=lambda item: item.stat().st_mtime)
    return files


def enforce_total_cap(paths: LogPaths, max_total_bytes: int) -> int:
    """Delete the oldest log files until the directory fits in the given size."""
    if max_total_bytes <= 0:
        return 0

    files = _log_files(paths)
    total = sum(path.stat().st_size for path in files)
    if total <= max_total_bytes:
        return 0

    removed = 0
    for path in files:
        if total <= max_total_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


def prune_logs(
    paths: LogPaths,
    keep_instances: int = 5,
    keep_helpers: int = 2,
    max_age_days: int = 14,
    max_total_bytes: Optional[int] = None,
) -> int:
    """Remove old run logs while keeping the newest files of each instance."""
    removed = _prune(paths.instances, _INSTANCE_RE, keep_instances, max_age_days)
    removed += _prune(paths.helpers, _HELPER_RE, keep_helpers, max_age_days)
    if max_total_bytes is not None:
        removed += enforce_total_cap(paths, max_total_bytes)
    return removed


def clear_log_directory(paths: LogPaths) -> int:
    """Delete every log file, keeping the directories in place."""
    removed = 0
    for path in _log_files(paths):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue

    for directory in (paths.instances, paths.helpers):
        latest = directory / "latest.log"
        try:
            if latest.is_symlink():
                latest.unlink()
        except OSError:
            pass
    return removed


def remove_log_directory(paths: LogPaths) -> bool:
    """Delete the whole log directory, used by the ``--clear-logs`` option."""
    try:
        if paths.root.is_dir():
            shutil.rmtree(paths.root)
            return True
    except OSError:
        return False
    return False
