"""Diagnostics gathered without starting GTK or opening a window."""

import json
import logging
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from src.core.config import Config
from src.core.utils import Utils

from .paths import LogPaths
from .redaction import redact_text
from .setup import LoggingHandle, get_logging_handle

_ENV_ALLOWLIST = (
    "HOME",
    "USER",
    "SHELL",
    "LANG",
    "LC_ALL",
    "PATH",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "DESKTOP_SESSION",
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "FLATPAK_ID",
)

_DEPENDENCIES = ("bwrap", "flatpak-spawn", "pasta", "gamescope", "steam", "python3", "xdg-open")


def _flatpak_info() -> dict[str, str]:
    path = Path("/.flatpak-info")
    if not path.is_file():
        return {}
    values = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key in {"app", "runtime", "arch", "branch", "app-path", "runtime-path"}:
                    values[key] = value
    except OSError:
        return {}
    return values


def _log_files(paths: Optional[LogPaths]) -> dict[str, Any]:
    if paths is None:
        return {}

    def count(directory: Path) -> int:
        if not directory.is_dir():
            return 0
        return len([path for path in directory.glob("*.log") if not path.is_symlink()])

    result: dict[str, Any] = {
        "main_log": str(paths.main_log),
        "crash_log": str(paths.crash_log),
        "main_log_bytes": paths.main_log.stat().st_size if paths.main_log.exists() else 0,
        "crash_log_bytes": paths.crash_log.stat().st_size if paths.crash_log.exists() else 0,
        "instance_logs": count(paths.instances),
        "helper_logs": count(paths.helpers),
    }
    return result


def _tail(path: Optional[Path], lines: int = 50) -> str:
    if path is None or not path.exists():
        return ""
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 32 * 1024))
            text = stream.read().decode("utf-8", "replace")
        return redact_text("\n".join(text.splitlines()[-lines:]))
    except OSError:
        return ""


def collect_diagnostics(handle: Optional[LoggingHandle] = None) -> dict[str, Any]:
    """Collect stable, privacy-conscious information for a bug report."""
    active = handle or get_logging_handle()
    paths = active.paths if active is not None else LogPaths.resolve()
    settings = active.settings if active is not None else None
    run_id = active.run_id if active is not None else "unconfigured"
    log_files = _log_files(paths)

    data: dict[str, Any] = {
        "application": {
            "name": "Twinverse",
            "version": Utils.get_version(),
            "pid": os.getpid(),
            "run_id": run_id,
            "base_path": str(Utils.get_base_path()),
        },
        "system": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "executable": sys.executable,
            "flatpak": Utils.is_flatpak(),
        },
        "flatpak": _flatpak_info(),
        "session": {
            "type": os.environ.get("XDG_SESSION_TYPE"),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY"),
            "display": os.environ.get("DISPLAY"),
            "wayland": Utils.is_wayland(),
        },
        "paths": {
            "config": str(Config.config_dir()),
            "data": str(Config.data_dir()),
            "cache": str(Config.cache_dir()),
            "state": str(Config.state_dir()),
            "logs": str(paths.root) if paths is not None else str(Config.logs_dir()),
        },
        "logging": {
            "enabled": active is not None and not active.closed,
            "directory": str(paths.root) if paths else None,
            "format": settings.format.value if settings else None,
            "console_level": logging.getLevelName(settings.console_level) if settings else None,
            "file_level": logging.getLevelName(settings.file_level) if settings else None,
            "console": active.console_enabled if active else None,
            "file": active.file_enabled if active else None,
        },
        "files": log_files,
        "environment": {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ},
        "dependencies": {name: shutil.which(name) for name in _DEPENDENCIES},
    }

    if paths is not None:
        data["recent_log"] = _tail(paths.main_log)
        data["crash_log"] = _tail(paths.crash_log, lines=80)
    else:
        data["recent_log"] = ""
        data["crash_log"] = ""

    return data


def format_diagnostics(data: dict[str, Any]) -> str:
    """Render diagnostics as a compact report for a support request."""
    lines = ["Twinverse diagnostics", ""]

    def section(title: str, values: dict[str, Any]) -> None:
        lines.append(f"[{title}]")
        for key, value in values.items():
            if value is None or value == "":
                continue
            if isinstance(value, dict):
                value = ", ".join(f"{k}={v}" for k, v in value.items())
            lines.append(f"{key}: {value}")
        lines.append("")

    for key in (
        "application",
        "system",
        "flatpak",
        "session",
        "paths",
        "logging",
        "files",
        "environment",
        "dependencies",
    ):
        section(key, data.get(key, {}))

    if data.get("recent_log"):
        lines.extend(["[recent log]", data["recent_log"], ""])
    if data.get("crash_log"):
        lines.extend(["[crash log]", data["crash_log"], ""])
    return "\n".join(lines).rstrip() + "\n"


def print_diagnostics(data: dict[str, Any], as_json: bool = False) -> None:
    """Write diagnostics to stdout, leaving stdout for data only."""
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, default=str))
    else:
        print(format_diagnostics(data), end="")
