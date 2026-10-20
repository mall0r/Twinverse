"""Logging settings loaded from the environment and the command line."""

import argparse
import logging
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional, Sequence


class LogFormat(str, Enum):
    """Supported output formats."""

    TEXT = "text"
    JSON = "json"


def parse_level(value: str) -> Optional[int]:
    """Return a logging level from a name or a number, or None when invalid."""
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized.isdigit():
        level = int(normalized)
        return level if 0 <= level <= logging.CRITICAL else None
    level = logging.getLevelName(normalized)
    return level if isinstance(level, int) else None


def _env_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(value: Optional[str], default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return min(maximum, max(minimum, parsed))


def _level_arg(value: str) -> int:
    level = parse_level(value)
    if level is None:
        raise argparse.ArgumentTypeError(f"invalid log level: {value}")
    return level


@dataclass(frozen=True)
class LogSettings:
    """Configuration of the logging subsystem.

    File logging stays at DEBUG by default. The console is friendlier and
    starts at INFO; ``--debug`` lowers both to DEBUG and ``--quiet`` raises
    the console to WARNING.
    """

    console_level: int = logging.INFO
    file_level: int = logging.DEBUG
    log_dir: Optional[Path] = None
    format: LogFormat = LogFormat.TEXT
    console: bool = True
    max_bytes: int = 2 * 1024 * 1024
    backup_count: int = 5
    instance_max_bytes: int = 100 * 1024 * 1024
    keep_instances: int = 5
    keep_helpers: int = 2
    max_age_days: int = 14
    max_total_bytes: int = 256 * 1024 * 1024
    debug: bool = False
    quiet: bool = False
    diagnostics: bool = False
    diagnostics_json: bool = False
    clear_logs: bool = False
    validation_warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Accept friendly strings when settings are built by callers."""
        if isinstance(self.format, str):
            object.__setattr__(self, "format", LogFormat(self.format.strip().lower()))
        if self.log_dir is not None and not isinstance(self.log_dir, Path):
            object.__setattr__(self, "log_dir", Path(self.log_dir).expanduser())

    @classmethod
    def from_environment(cls, environ: Optional[Mapping[str, str]] = None) -> "LogSettings":
        """Build settings from ``TWINVERSE_*`` environment variables."""
        env = os.environ if environ is None else environ
        warnings = []

        debug = _env_bool(env.get("TWINVERSE_DEBUG"), False)
        console_level = logging.DEBUG if debug else logging.INFO
        file_level = logging.DEBUG

        raw_level = env.get("TWINVERSE_LOG_LEVEL")
        if raw_level:
            parsed = parse_level(raw_level)
            if parsed is None:
                warnings.append(
                    f"TWINVERSE_LOG_LEVEL={raw_level!r} is invalid; using {logging.getLevelName(console_level)}"
                )
            else:
                console_level = parsed

        raw_file_level = env.get("TWINVERSE_LOG_FILE_LEVEL")
        if raw_file_level:
            parsed = parse_level(raw_file_level)
            if parsed is None:
                warnings.append(
                    f"TWINVERSE_LOG_FILE_LEVEL={raw_file_level!r} is invalid; using {logging.getLevelName(file_level)}"
                )
            else:
                file_level = parsed

        if debug:
            console_level = logging.DEBUG
            file_level = logging.DEBUG

        log_dir = None
        raw_dir = env.get("TWINVERSE_LOG_DIR")
        if raw_dir:
            log_dir = Path(raw_dir).expanduser()

        raw_format = env.get("TWINVERSE_LOG_FORMAT")
        log_format = LogFormat.TEXT
        if raw_format:
            try:
                log_format = LogFormat(raw_format.strip().lower())
            except ValueError:
                warnings.append(f"TWINVERSE_LOG_FORMAT={raw_format!r} is invalid; using text")

        return cls(
            console_level=console_level,
            file_level=file_level,
            log_dir=log_dir,
            format=log_format,
            console=_env_bool(env.get("TWINVERSE_LOG_CONSOLE"), True),
            max_bytes=_env_int(env.get("TWINVERSE_LOG_MAX_BYTES"), 2 * 1024 * 1024, 64 * 1024, 1024**3),
            backup_count=_env_int(env.get("TWINVERSE_LOG_BACKUPS"), 5, 0, 50),
            instance_max_bytes=_env_int(
                env.get("TWINVERSE_INSTANCE_LOG_MAX_BYTES"), 100 * 1024 * 1024, 1024 * 1024, 4 * 1024**3
            ),
            keep_instances=_env_int(env.get("TWINVERSE_LOG_KEEP_INSTANCES"), 5, 1, 100),
            keep_helpers=_env_int(env.get("TWINVERSE_LOG_KEEP_HELPERS"), 2, 1, 100),
            max_age_days=_env_int(env.get("TWINVERSE_LOG_MAX_AGE_DAYS"), 14, 1, 365),
            max_total_bytes=_env_int(env.get("TWINVERSE_LOG_MAX_TOTAL_MB"), 256, 1, 1024 * 1024) * 1024 * 1024,
            debug=debug,
            validation_warnings=tuple(warnings),
        )

    @classmethod
    def from_argv(cls, argv: Sequence[str], version: str) -> tuple["LogSettings", list[str]]:
        """Parse Twinverse options and return settings plus the GUI arguments."""
        parser = argparse.ArgumentParser(
            prog="twinverse",
            description="Twinverse - multiple isolated Steam instances.",
            epilog="See docs/DEBUGGING.md for log locations and environment variables.",
        )
        parser.add_argument("--debug", action="store_true", help="enable DEBUG logging on the console and in the file")
        parser.add_argument("--quiet", action="store_true", help="only show warnings and errors on the console")
        parser.add_argument("--log-level", type=_level_arg, metavar="LEVEL", help="console log level (name or number)")
        parser.add_argument(
            "--log-dir", type=Path, metavar="DIR", help="write logs to DIR instead of the XDG state path"
        )
        parser.add_argument(
            "--log-format",
            choices=[item.value for item in LogFormat],
            help="log file and console format",
        )
        parser.add_argument("--json", action="store_true", help="use JSON for logs and diagnostics")
        parser.add_argument(
            "--diagnostics", action="store_true", help="print diagnostics and exit without opening the GUI"
        )
        parser.add_argument(
            "--clear-logs", action="store_true", help="delete every log file and exit without opening the GUI"
        )
        parser.add_argument("--version", action="version", version=f"Twinverse {version}")

        args, remaining = parser.parse_known_args(argv)
        settings = cls.from_environment()

        if args.debug:
            settings = replace(settings, debug=True, console_level=logging.DEBUG, file_level=logging.DEBUG)
        if args.quiet:
            settings = replace(settings, quiet=True, debug=False)
            if args.log_level is None:
                settings = replace(settings, console_level=logging.WARNING)
        if args.log_level is not None:
            settings = replace(settings, console_level=args.log_level)
        if args.log_dir is not None:
            settings = replace(settings, log_dir=args.log_dir.expanduser())
        if args.log_format is not None:
            settings = replace(settings, format=LogFormat(args.log_format))
        if args.json:
            settings = replace(settings, format=LogFormat.JSON, diagnostics_json=True)
        if args.diagnostics:
            settings = replace(settings, diagnostics=True)
        if args.clear_logs:
            settings = replace(settings, clear_logs=True)

        return settings, remaining
