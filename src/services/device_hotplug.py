"""Live hardware hotplug monitor for input devices and connected displays."""

from __future__ import annotations

import ctypes
import errno
import logging
import os
import selectors
import struct
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib  # noqa: E402

logger = logging.getLogger(__name__)

# Linux inotify constants (<sys/inotify.h>)
_IN_NONBLOCK = 0o4000
_IN_CLOEXEC = 0o2000000
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_IGNORED = 0x00008000

_WATCH_MASK = _IN_CREATE | _IN_DELETE | _IN_MOVED_TO | _IN_MOVED_FROM | _IN_DELETE_SELF
_INOTIFY_EVENT_HEADER = struct.Struct("iIII")

DEFAULT_WATCH_DIRS: tuple[Path, ...] = (Path("/dev/input"), Path("/dev/input/by-id"))
DEFAULT_DEBOUNCE_SECONDS = 0.35


def _load_inotify_libc() -> Optional[Any]:
    """Return a ctypes handle to libc with inotify signatures configured, or None."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_add_watch.restype = ctypes.c_int
        return libc
    except (OSError, AttributeError):
        return None


def _is_relevant_input_event(watched_dir: Path, name: bytes, mask: int) -> bool:
    """Return True if an inotify event in ``watched_dir`` can affect detected input devices."""
    if mask & (_IN_DELETE_SELF | _IN_IGNORED):
        return True
    if watched_dir != Path("/dev/input"):
        return True
    if not name:
        return True
    return name == b"by-id" or name.startswith(b"event") or name.startswith(b"js")


class DeviceHotplugMonitor:
    """Watch Linux input hotplug events and GTK4 display changes, coalescing bursts."""

    def __init__(
        self,
        on_change: Callable[[], None],
        *,
        watch_dirs: tuple[Path, ...] = DEFAULT_WATCH_DIRS,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        watch_displays: bool = True,
        display_provider: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize the hotplug monitor without starting watchers."""
        self._on_change = on_change
        self._watch_dirs = tuple(Path(p) for p in watch_dirs)
        self._debounce_seconds = max(0.0, float(debounce_seconds))
        self._watch_displays = bool(watch_displays)
        self._display_provider = display_provider or Gdk.Display.get_default

        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._wake_r: Optional[int] = None
        self._wake_w: Optional[int] = None
        self._inotify_fd: Optional[int] = None
        self._libc: Optional[Any] = None
        self._wd_to_path: dict[int, Path] = {}
        self._watched_paths: set[Path] = set()

        # GTK main-thread display tracking
        self._monitors_model: Optional[Any] = None
        self._monitors_changed_handler = 0
        self._monitor_handlers: dict[int, tuple[Any, list[int]]] = {}
        self._display_timeout_id = 0

    @property
    def is_running(self) -> bool:
        """Return whether the hotplug monitor is active."""
        with self._lock:
            return self._running

    def start(self) -> None:
        """Start monitoring input device nodes and display outputs."""
        with self._lock:
            if self._running:
                return
            self._running = True

        if self._watch_displays:
            self._start_display_watch()

        self._start_input_watch()

    def stop(self) -> None:
        """Stop all input and display watchers cleanly."""
        thread: Optional[threading.Thread] = None
        with self._lock:
            if not self._running:
                return
            self._running = False
            thread = self._thread
            self._thread = None
            self._wake_locked()

        self._stop_display_watch()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        with self._lock:
            self._close_input_fds_locked()

    def _emit_change(self) -> None:
        with self._lock:
            if not self._running:
                return
        try:
            self._on_change()
        except Exception:
            logger.exception("Error invoking device hotplug callback")

    # ------------------------------------------------------------------
    # Input hotplug (Linux inotify)
    # ------------------------------------------------------------------

    def _start_input_watch(self) -> None:
        if not self._watch_dirs:
            return
        libc = _load_inotify_libc()
        if libc is None:
            logger.debug("Linux inotify unavailable; automatic input hotplug disabled")
            return

        inotify_fd = int(libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC))
        if inotify_fd < 0:
            err = ctypes.get_errno()
            logger.warning("inotify_init1 failed (errno=%s); automatic input hotplug disabled", err)
            return

        try:
            wake_r, wake_w = os.pipe()
            os.set_blocking(wake_r, False)
            os.set_blocking(wake_w, False)
        except OSError:
            os.close(inotify_fd)
            logger.exception("Failed to create wakeup pipe for device hotplug monitor")
            return

        with self._lock:
            if not self._running:
                os.close(inotify_fd)
                os.close(wake_r)
                os.close(wake_w)
                return
            self._libc = libc
            self._inotify_fd = inotify_fd
            self._wake_r = wake_r
            self._wake_w = wake_w
            self._ensure_watches_locked()
            self._thread = threading.Thread(
                target=self._run_inotify_loop,
                name="twinverse-device-hotplug",
                daemon=True,
            )
            self._thread.start()
            logger.debug("Input hotplug monitor started for %s", [str(p) for p in self._watch_dirs])

    def _ensure_watches_locked(self) -> None:
        if self._inotify_fd is None or self._libc is None:
            return
        for path in self._watch_dirs:
            if path in self._watched_paths or not path.is_dir():
                continue
            wd = int(self._libc.inotify_add_watch(self._inotify_fd, os.fsencode(path), _WATCH_MASK))
            if wd >= 0:
                self._wd_to_path[wd] = path
                self._watched_paths.add(path)

    def _wake_locked(self) -> None:
        if self._wake_w is None:
            return
        try:
            os.write(self._wake_w, b"w")
        except OSError:
            pass

    def _drain_wakeup(self) -> None:
        wake_r = self._wake_r
        if wake_r is None:
            return
        while True:
            try:
                chunk = os.read(wake_r, 64)
                if not chunk:
                    break
            except BlockingIOError:
                break
            except OSError:
                break

    def _close_input_fds_locked(self) -> None:
        for attr in ("_inotify_fd", "_wake_r", "_wake_w"):
            fd = getattr(self, attr)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, attr, None)
        self._wd_to_path.clear()
        self._watched_paths.clear()

    def _drain_inotify_events(self) -> bool:
        """Read pending inotify events and return True if any relevant change occurred."""
        fd = self._inotify_fd
        if fd is None:
            return False

        raw = bytearray()
        while True:
            try:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                raw.extend(chunk)
            except BlockingIOError:
                break
            except OSError:
                break

        if not raw:
            return False

        relevant = False
        offset = 0
        hdr_size = _INOTIFY_EVENT_HEADER.size
        total = len(raw)

        with self._lock:
            while offset + hdr_size <= total:
                wd, mask, _cookie, name_len = _INOTIFY_EVENT_HEADER.unpack_from(raw, offset)
                offset += hdr_size
                end = min(total, offset + name_len)
                name = bytes(raw[offset:end]).rstrip(b"\x00")
                offset = end

                watched_dir = self._wd_to_path.get(wd)
                if mask & (_IN_IGNORED | _IN_DELETE_SELF):
                    removed = self._wd_to_path.pop(wd, None)
                    if removed is not None:
                        self._watched_paths.discard(removed)

                if watched_dir is None or _is_relevant_input_event(watched_dir, name, mask):
                    relevant = True

            # Re-register watches (e.g. if /dev/input/by-id was just created).
            self._ensure_watches_locked()

        return relevant

    def _run_inotify_loop(self) -> None:
        selector = selectors.DefaultSelector()
        try:
            with self._lock:
                wake_r = self._wake_r
                inotify_fd = self._inotify_fd
            if wake_r is None or inotify_fd is None:
                return
            selector.register(wake_r, selectors.EVENT_READ, data="wake")
            selector.register(inotify_fd, selectors.EVENT_READ, data="inotify")

            pending_deadline: Optional[float] = None

            while True:
                with self._lock:
                    if not self._running:
                        break

                timeout: Optional[float] = None
                if pending_deadline is not None:
                    remaining = pending_deadline - time.monotonic()
                    if remaining <= 0.0:
                        pending_deadline = None
                        self._emit_change()
                        continue
                    timeout = remaining

                try:
                    ready = selector.select(timeout=timeout)
                except OSError as exc:
                    if exc.errno == errno.EINTR:
                        continue
                    logger.debug("Input hotplug selector stopped: %s", exc)
                    break

                if not ready:
                    if pending_deadline is not None and time.monotonic() >= pending_deadline:
                        pending_deadline = None
                        self._emit_change()
                    continue

                for key, _events in ready:
                    if key.data == "wake":
                        self._drain_wakeup()
                    elif key.data == "inotify":
                        if self._drain_inotify_events():
                            if self._debounce_seconds <= 0.0:
                                self._emit_change()
                            else:
                                pending_deadline = time.monotonic() + self._debounce_seconds
        finally:
            selector.close()

    # ------------------------------------------------------------------
    # Display / Monitor hotplug (GTK4 Gdk.Display)
    # ------------------------------------------------------------------

    def _start_display_watch(self) -> None:
        try:
            display = self._display_provider()
        except Exception:
            logger.debug("Unable to query Gdk.Display for monitor hotplug", exc_info=True)
            return
        if display is None:
            return
        monitors = display.get_monitors()
        if monitors is None:
            return

        self._monitors_model = monitors
        self._monitors_changed_handler = monitors.connect("items-changed", self._on_monitors_items_changed)
        self._sync_monitor_signal_handlers()
        logger.debug("Display hotplug monitor connected to Gdk.Display")

    def _stop_display_watch(self) -> None:
        if self._display_timeout_id:
            try:
                GLib.source_remove(self._display_timeout_id)
            except Exception:
                pass
            self._display_timeout_id = 0

        if self._monitors_model is not None and self._monitors_changed_handler:
            try:
                self._monitors_model.disconnect(self._monitors_changed_handler)
            except Exception:
                pass
        self._monitors_changed_handler = 0
        self._monitors_model = None

        for monitor, handlers in list(self._monitor_handlers.values()):
            for handler_id in handlers:
                try:
                    monitor.disconnect(handler_id)
                except Exception:
                    pass
        self._monitor_handlers.clear()

    def _iter_monitors(self) -> list[Any]:
        model = self._monitors_model
        if model is None:
            return []
        if hasattr(model, "get_n_items") and hasattr(model, "get_item"):
            items = []
            for idx in range(model.get_n_items()):
                item = model.get_item(idx)
                if item is not None:
                    items.append(item)
            return items
        return list(model)

    def _sync_monitor_signal_handlers(self) -> None:
        current = self._iter_monitors()
        current_ids = {id(m) for m in current}

        for monitor_id in list(self._monitor_handlers):
            if monitor_id not in current_ids:
                monitor, old_handlers = self._monitor_handlers.pop(monitor_id)
                for handler_id in old_handlers:
                    try:
                        monitor.disconnect(handler_id)
                    except Exception:
                        pass

        for monitor in current:
            monitor_id = id(monitor)
            if monitor_id in self._monitor_handlers:
                continue
            handlers: list[int] = []
            for signal_name in ("notify::geometry", "notify::refresh-rate"):
                try:
                    handlers.append(monitor.connect(signal_name, self._on_monitor_property_changed))
                except Exception:
                    pass
            self._monitor_handlers[monitor_id] = (monitor, handlers)

    def _on_monitors_items_changed(self, _model, _position: int, _removed: int, _added: int) -> None:
        self._sync_monitor_signal_handlers()
        self._schedule_display_change()

    def _on_monitor_property_changed(self, _monitor, _pspec=None) -> None:
        self._schedule_display_change()

    def _schedule_display_change(self) -> None:
        if not self.is_running:
            return
        if self._debounce_seconds <= 0.0:
            self._emit_change()
            return
        if self._display_timeout_id:
            try:
                GLib.source_remove(self._display_timeout_id)
            except Exception:
                pass
            self._display_timeout_id = 0
        delay_ms = max(1, int(self._debounce_seconds * 1000))
        self._display_timeout_id = GLib.timeout_add(delay_ms, self._on_display_debounce_timeout)

    def _on_display_debounce_timeout(self) -> bool:
        self._display_timeout_id = 0
        self._emit_change()
        return False
