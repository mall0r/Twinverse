"""Configure standard-library logging once, at the application entry point."""

import atexit
import faulthandler
import logging
import os
import secrets
import sys
import threading
from dataclasses import dataclass, field
from types import TracebackType
from typing import IO, Any, Callable, Optional, Type

from src.core.config import Config

from .context import set_run_id
from .filters import ContextFilter, NamespaceFilter
from .formatters import JsonFormatter, TextFormatter
from .handlers import PrivateRotatingFileHandler, SafeStderrHandler
from .paths import LogPaths
from .retention import prune_logs
from .settings import LogFormat, LogSettings

ExceptionHook = Callable[[Type[BaseException], BaseException, Optional[TracebackType]], Any]
ThreadingHook = Callable[[threading.ExceptHookArgs], Any]
# ``sys.UnraisableHookArgs`` is not exposed by every supported Python release.
UnraisableHook = Callable[[Any], Any]


@dataclass
class LoggingHandle:
    """The state needed to shut down a configured logging session."""

    settings: LogSettings
    paths: Optional[LogPaths]
    run_id: str
    root: logging.Logger
    source_logger: logging.Logger
    handlers: list[logging.Handler] = field(default_factory=list)
    file_enabled: bool = False
    console_enabled: bool = False
    old_root_level: int = logging.WARNING
    old_source_level: int = logging.NOTSET
    old_raise_exceptions: bool = True
    crash_file: Optional[IO[bytes]] = None
    original_excepthook: Optional[ExceptionHook] = None
    original_threading_excepthook: Optional[ThreadingHook] = None
    original_unraisablehook: Optional[UnraisableHook] = None
    closed: bool = False

    def shutdown(self) -> None:
        """Flush and detach everything installed by :func:`configure_logging`."""
        if self.closed:
            return
        self.closed = True

        logger = logging.getLogger("src.core.logging")
        try:
            logger.debug("Logging stopped (run=%s)", self.run_id)
        except Exception:
            pass

        for handler in self.handlers:
            try:
                handler.flush()
                self.root.removeHandler(handler)
                handler.close()
            except Exception:
                pass
        self.handlers.clear()

        self.root.setLevel(self.old_root_level)
        self.source_logger.setLevel(self.old_source_level)
        logging.raiseExceptions = self.old_raise_exceptions
        logging.captureWarnings(False)

        try:
            faulthandler.disable()
        except Exception:
            pass
        if self.crash_file is not None:
            try:
                self.crash_file.close()
            except Exception:
                pass
            self.crash_file = None

        if self.original_excepthook is not None:
            sys.excepthook = self.original_excepthook
        if self.original_threading_excepthook is not None:
            threading.excepthook = self.original_threading_excepthook
        if self.original_unraisablehook is not None:
            sys.unraisablehook = self.original_unraisablehook
        set_run_id(None)


_handle: Optional[LoggingHandle] = None
_atexit_registered = False


def _fallback_paths() -> Optional[LogPaths]:
    fallback = LogPaths.resolve(Config.runtime_dir() / "logs")
    try:
        fallback.ensure()
        return fallback
    except OSError:
        return None


def _install_exception_hooks(handle: LoggingHandle) -> None:
    logger = logging.getLogger("src.core.logging")

    handle.original_excepthook = sys.excepthook
    handle.original_threading_excepthook = getattr(threading, "excepthook", None)
    handle.original_unraisablehook = getattr(sys, "unraisablehook", None)

    def excepthook(exc_type, exc_value, traceback):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            handle.original_excepthook(exc_type, exc_value, traceback)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, traceback))
        # The standard hook still prints the traceback, so the failure is
        # visible on the console and not only in the log file.
        handle.original_excepthook(exc_type, exc_value, traceback)

    def threading_excepthook(args):
        if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
            if handle.original_threading_excepthook:
                handle.original_threading_excepthook(args)
            return
        logger.critical(
            "Unhandled exception in thread %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if handle.original_threading_excepthook:
            handle.original_threading_excepthook(args)

    def unraisablehook(unraisable):
        if unraisable.exc_value is not None:
            logger.error(
                "Unraisable exception in %s",
                unraisable.object,
                exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback),
            )
        if handle.original_unraisablehook:
            handle.original_unraisablehook(unraisable)

    sys.excepthook = excepthook
    if handle.original_threading_excepthook is not None:
        threading.excepthook = threading_excepthook
    if handle.original_unraisablehook is not None:
        sys.unraisablehook = unraisablehook


def _build_handlers(settings: LogSettings, paths: Optional[LogPaths], handle: LoggingHandle) -> None:
    formatter = JsonFormatter() if settings.format is LogFormat.JSON else TextFormatter()
    context_filter = ContextFilter()
    namespace_filter = NamespaceFilter()

    if settings.console and sys.stderr is not None:
        console = SafeStderrHandler(sys.stderr)
        console.setLevel(settings.console_level)
        console.addFilter(context_filter)
        console.addFilter(namespace_filter)
        console.setFormatter(formatter)
        handle.root.addHandler(console)
        handle.handlers.append(console)
        handle.console_enabled = True

    if paths is not None:
        try:
            file_handler = PrivateRotatingFileHandler(
                paths.main_log,
                maxBytes=settings.max_bytes,
                backupCount=settings.backup_count,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setLevel(settings.file_level)
            file_handler.addFilter(context_filter)
            file_handler.addFilter(namespace_filter)
            file_handler.setFormatter(formatter)
            handle.root.addHandler(file_handler)
            handle.handlers.append(file_handler)
            handle.file_enabled = True
        except OSError as error:
            sys.stderr.write(f"Twinverse: file logging disabled: {error}\n")

    if not handle.handlers:
        handle.root.addHandler(logging.NullHandler())


def configure_logging(settings: Optional[LogSettings] = None) -> LoggingHandle:
    """Install logging handlers and exception hooks, idempotently."""
    global _handle, _atexit_registered

    if _handle is not None and not _handle.closed:
        return _handle

    settings = settings or LogSettings.from_environment()
    run_id = secrets.token_hex(4)
    set_run_id(run_id)

    resolved = LogPaths.resolve(settings.log_dir)
    try:
        resolved.ensure()
    except OSError as error:
        sys.stderr.write(f"Twinverse: could not create {resolved.root}: {error}\n")
        fallback = _fallback_paths()
        if fallback is not None:
            sys.stderr.write(f"Twinverse: using fallback log directory {fallback.root}\n")
            paths: Optional[LogPaths] = fallback
        else:
            paths = None
    else:
        paths = resolved

    root = logging.getLogger()
    source_logger = logging.getLogger("src")
    handle = LoggingHandle(
        settings=settings,
        paths=paths,
        run_id=run_id,
        root=root,
        source_logger=source_logger,
        old_root_level=root.level,
        old_source_level=source_logger.level,
        old_raise_exceptions=logging.raiseExceptions,
    )

    root.setLevel(logging.DEBUG if settings.debug else logging.WARNING)
    source_logger.setLevel(min(settings.console_level, settings.file_level))
    logging.raiseExceptions = False
    logging.captureWarnings(True)

    _build_handlers(settings, paths, handle)
    if paths is not None:
        try:
            removed = prune_logs(paths)
            if removed:
                logging.getLogger("src.core.logging").debug("Removed %s old run log(s)", removed)
        except OSError:
            pass

    _install_exception_hooks(handle)

    if paths is not None:
        try:
            descriptor = os.open(paths.crash_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            handle.crash_file = os.fdopen(descriptor, "ab")
            faulthandler.enable(file=handle.crash_file, all_threads=True)
        except OSError as error:
            logging.getLogger("src.core.logging").warning("Could not enable crash logging: %s", error)

    logger = logging.getLogger("src.core.logging")
    for warning in settings.validation_warnings:
        logger.warning("%s", warning)
    logger.debug(
        "Logging configured (run=%s, directory=%s, format=%s, console=%s, file=%s)",
        run_id,
        paths.root if paths else "disabled",
        settings.format.value,
        handle.console_enabled,
        handle.file_enabled,
    )

    if not _atexit_registered:
        atexit.register(_shutdown_handle)
        _atexit_registered = True

    _handle = handle
    return handle


def _shutdown_handle() -> None:
    if _handle is not None:
        _handle.shutdown()


def reset_logging() -> None:
    """Shut down the current logging session. Intended for tests."""
    global _handle
    if _handle is not None:
        _handle.shutdown()
        _handle = None
    else:
        set_run_id(None)


def get_logging_handle() -> Optional[LoggingHandle]:
    """Return the active logging handle, if the entry point configured one."""
    return _handle


def get_log_paths() -> Optional[LogPaths]:
    """Return the active log layout, or the default one before setup."""
    if _handle is not None and not _handle.closed:
        return _handle.paths
    return LogPaths.resolve()


def get_run_id() -> str:
    """Return the active run identifier."""
    return _handle.run_id if _handle is not None and not _handle.closed else "unconfigured"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return an application logger without configuring anything."""
    return logging.getLogger(name or "src")
