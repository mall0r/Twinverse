"""Background gamepad monitor for the global session-exit shortcut (HOME + L3)."""

from __future__ import annotations

import errno
import logging
import os
import selectors
import socket
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

try:
    import evdev
except ImportError:  # pragma: no cover - optional runtime dependency fallback
    evdev = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Standard Linux input event types and key/axis codes (from linux/input-event-codes.h)
EV_KEY = 1
EV_ABS = 3

BTN_SOUTH = 304  # A / Cross (also BTN_GAMEPAD)
BTN_EAST = 305  # B / Circle
BTN_MODE = 316  # Home / Guide / PS / Steam
BTN_THUMBL = 317  # L3 / left stick click
BTN_DPAD_LEFT = 546
BTN_DPAD_RIGHT = 547

KEY_HOMEPAGE = 172  # Home on some D-Input / Android controllers

ABS_X = 0
ABS_HAT0X = 16

HOME_CODES = frozenset({BTN_MODE, KEY_HOMEPAGE})
CONFIRM_CODES = frozenset({BTN_SOUTH})
CANCEL_CODES = frozenset({BTN_EAST})
DPAD_LEFT_CODES = frozenset({BTN_DPAD_LEFT})
DPAD_RIGHT_CODES = frozenset({BTN_DPAD_RIGHT})

_IGNORED_DEVICE_SUBSTRINGS = (
    "twinverse",
    "steam virtual gamepad",
)

# Binary layout constants matching `twinverse-uinput-proto` (`UdynDesc` & `NativeInputEvent`).
_BRIDGE_KEY_PREFIX = "bridge:"
_UDYN_DESC_MAGIC = 0x54575549
_UDYN_DESC_VERSION = 1
_UDYN_DESC_NAME_OFFSET = 16
_UDYN_DESC_NAME_LEN = 80
_UDYN_DESC_ABSINFO_OFFSET = 212
_UDYN_DESC_EVENT_SIZE_OFFSET = 1748
_UDYN_DESC_MIN_SIZE = 1752
_INPUT_EVENT_64 = struct.Struct("<qqHHi")
_INPUT_EVENT_32 = struct.Struct("<iiHHi")
_INPUT_EVENT_NATIVE = struct.Struct("llHHi")
_TWCTL_REGISTER_MONITOR = b"TWCTL\x01\x00\x00"
_TWCTL_MUTE_SANDBOX = b"TWCTL\x02\x01\x00"
_TWCTL_UNMUTE_SANDBOX = b"TWCTL\x02\x00\x00"

DEFAULT_RESCAN_INTERVAL = 1.5
DEFAULT_NAV_GRACE_SECONDS = 0.35
_STICK_ENGAGE_THRESHOLD = 0.6
_STICK_RELEASE_THRESHOLD = 0.35


@dataclass
class _DeviceState:
    """Tracked button and axis state for one physical gamepad."""

    home_held: bool = False
    l3_held: bool = False
    stick_x_dir: int = 0
    hat_x_dir: int = 0
    abs_x_min: int = -32768
    abs_x_max: int = 32767


def _is_ignored_device_name(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in _IGNORED_DEVICE_SUBSTRINGS)


def _is_gamepad_capabilities(capabilities: dict[int, Any]) -> bool:
    """Return True if an evdev capabilities dict looks like a physical gamepad."""
    keys = set(capabilities.get(EV_KEY, ()))
    if not keys:
        return False
    if BTN_SOUTH in keys:
        return True
    return bool(keys & HOME_CODES) and BTN_THUMBL in keys


def _normalize_axis(value: int, axis_min: int, axis_max: int) -> float:
    """Normalize a raw ABS_X reading into [-1.0, 1.0]."""
    span = axis_max - axis_min
    if span <= 0:
        return 0.0
    midpoint = (axis_max + axis_min) / 2.0
    half_span = span / 2.0
    normalized = (value - midpoint) / half_span
    return max(-1.0, min(1.0, normalized))


def _parse_bridge_desc(desc_path: Path) -> tuple[tuple[int, int], struct.Struct, str]:
    """Read ABS_X bounds, input_event record layout, and device name from a bridge ``.desc`` file."""
    abs_range = (-32768, 32767)
    event_struct = _INPUT_EVENT_NATIVE
    device_name = ""
    try:
        data = desc_path.read_bytes()
    except OSError:
        return abs_range, event_struct, device_name
    if len(data) < _UDYN_DESC_ABSINFO_OFFSET + 24:
        return abs_range, event_struct, device_name
    magic, version = struct.unpack_from("<II", data, 0)
    if magic != _UDYN_DESC_MAGIC or version != _UDYN_DESC_VERSION:
        return abs_range, event_struct, device_name
    raw_name = data[_UDYN_DESC_NAME_OFFSET : _UDYN_DESC_NAME_OFFSET + _UDYN_DESC_NAME_LEN]
    device_name = raw_name.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    _val, abs_min, abs_max, _fuzz, _flat, _res = struct.unpack_from("<iiiiii", data, _UDYN_DESC_ABSINFO_OFFSET)
    if abs_max > abs_min:
        abs_range = (int(abs_min), int(abs_max))
    if len(data) >= _UDYN_DESC_MIN_SIZE:
        (event_size,) = struct.unpack_from("<I", data, _UDYN_DESC_EVENT_SIZE_OFFSET)
        if event_size == _INPUT_EVENT_64.size:
            event_struct = _INPUT_EVENT_64
        elif event_size == _INPUT_EVENT_32.size:
            event_struct = _INPUT_EVENT_32
    return abs_range, event_struct, device_name


class _BridgeSocketDevice:
    """Stream client for a ``twinverse-input-bridge`` Unix socket (``tw_event3000.sock``).

    When the bridge holds an exclusive ``EVIOCGRAB`` on the physical controller to
    isolate it from Host Steam, raw ``/dev/input/event*`` readers stop receiving
    events; subscribing to the bridge socket lets the exit shortcut and overlay
    navigation keep working transparently.
    """

    def __init__(
        self,
        sock: socket.socket,
        sock_path: Path,
        abs_x_range: tuple[int, int],
        event_struct: struct.Struct,
    ) -> None:
        self._sock = sock
        self.name = f"twinverse-input-bridge ({sock_path.parent.parent.parent.name})"
        self._abs_x_min, self._abs_x_max = abs_x_range
        self._event_struct = event_struct
        self._buf = bytearray()
        self._sandbox_muted = False

    @classmethod
    def connect(cls, sock_path: Path) -> Optional[_BridgeSocketDevice]:
        """Connect to a live bridge socket, returning ``None`` if unavailable or ignored."""
        abs_range, event_struct, device_name = _parse_bridge_desc(sock_path.with_suffix(".desc"))
        if device_name and _is_ignored_device_name(device_name):
            return None

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dir_fd: Optional[int] = None
        try:
            target = str(sock_path)
            if len(os.fsencode(target)) >= 108:
                dir_fd = os.open(sock_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                target = f"/proc/self/fd/{dir_fd}/{sock_path.name}"
            sock.settimeout(0.2)
            sock.connect(target)
            sock.sendall(_TWCTL_REGISTER_MONITOR)
            sock.setblocking(False)
        except OSError:
            sock.close()
            return None
        finally:
            if dir_fd is not None:
                try:
                    os.close(dir_fd)
                except OSError:
                    pass

        return cls(sock, sock_path, abs_range, event_struct)

    @property
    def fd(self) -> int:
        return self._sock.fileno()

    def absinfo(self, code: int) -> Optional[SimpleNamespace]:
        if code == ABS_X:
            return SimpleNamespace(min=self._abs_x_min, max=self._abs_x_max)
        return None

    def read(self) -> list[SimpleNamespace]:
        while True:
            try:
                chunk = self._sock.recv(4096)
            except BlockingIOError:
                break
            if not chunk:
                raise OSError(errno.ECONNRESET, "Input bridge socket closed")
            self._buf.extend(chunk)
            if len(chunk) < 4096:
                break

        rec_size = self._event_struct.size
        count = len(self._buf) // rec_size
        if count <= 0:
            return []

        events: list[SimpleNamespace] = []
        unpack_from = self._event_struct.unpack_from
        for idx in range(count):
            _sec, _usec, ev_type, code, value = unpack_from(self._buf, idx * rec_size)
            events.append(SimpleNamespace(type=ev_type, code=code, value=value))
        del self._buf[: count * rec_size]
        return events

    def set_sandbox_muted(self, muted: bool) -> bool:
        """Mute or unmute sandbox clients on this controller bridge."""
        muted = bool(muted)
        if self._sandbox_muted == muted:
            return True
        packet = _TWCTL_MUTE_SANDBOX if muted else _TWCTL_UNMUTE_SANDBOX
        try:
            self._sock.sendall(packet)
        except OSError:
            logger.debug("Failed to set sandbox mute=%s on %s", muted, self.name, exc_info=True)
            return False
        self._sandbox_muted = muted
        return True

    def close(self) -> None:
        if self._sandbox_muted:
            self.set_sandbox_muted(False)
        try:
            self._sock.close()
        except OSError:
            pass


class ControllerShortcutMonitor:
    """Watch connected gamepads for HOME + L3 and modal navigation."""

    def __init__(
        self,
        on_trigger: Callable[[], None],
        on_navigate: Optional[Callable[[str], None]] = None,
        *,
        rescan_interval: float = DEFAULT_RESCAN_INTERVAL,
        nav_grace_seconds: float = DEFAULT_NAV_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        device_enumerator: Optional[Callable[[], list[str]]] = None,
        device_opener: Optional[Callable[[str], Any]] = None,
        bridge_socket_enumerator: Optional[Callable[[], list[str]]] = None,
    ) -> None:
        """Initialize the shortcut monitor without starting its background thread."""
        self._on_trigger = on_trigger
        self._on_navigate = on_navigate
        self._rescan_interval = max(0.2, float(rescan_interval))
        self._nav_grace_seconds = max(0.0, float(nav_grace_seconds))
        self._clock = clock
        self._device_enumerator = device_enumerator
        self._device_opener = device_opener
        self._bridge_socket_enumerator = bridge_socket_enumerator

        self._lock = threading.RLock()
        self._running = False
        self._navigation_mode = False
        self._nav_enabled_at = 0.0
        self._nav_device_key: Optional[str] = None
        self._muted_device_key: Optional[str] = None
        self._rescan_requested = False
        self._thread: Optional[threading.Thread] = None
        self._wake_r: Optional[int] = None
        self._wake_w: Optional[int] = None
        self._devices: dict[str, Any] = {}
        self._states: dict[str, _DeviceState] = {}

    @property
    def is_running(self) -> bool:
        """Return whether the background monitoring loop is active."""
        with self._lock:
            return self._running

    @property
    def navigation_mode(self) -> bool:
        """Return whether controller events are routed to the confirmation overlay."""
        with self._lock:
            return self._navigation_mode

    @property
    def active_navigation_device(self) -> Optional[str]:
        """Return the device key currently locked to control the confirmation overlay, if any."""
        with self._lock:
            return self._nav_device_key

    def start(self) -> None:
        """Start monitoring connected gamepads in a daemon thread."""
        with self._lock:
            if self._running:
                return
            if evdev is None and self._device_enumerator is None and self._bridge_socket_enumerator is None:
                logger.warning("python-evdev is not installed; controller exit shortcut disabled")
                return
            try:
                wake_r, wake_w = os.pipe()
                os.set_blocking(wake_r, False)
                os.set_blocking(wake_w, False)
            except OSError:
                logger.exception("Failed to create wakeup pipe for controller shortcut monitor")
                return
            self._wake_r = wake_r
            self._wake_w = wake_w
            self._rescan_requested = False
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name="twinverse-shortcut-monitor",
                daemon=True,
            )
            self._thread.start()
            logger.debug("Controller shortcut monitor started")

    def wake(self, *, rescan: bool = False) -> None:
        """Wake the background selector loop, optionally requesting an immediate device rescan."""
        with self._lock:
            if not self._running:
                return
            if rescan:
                self._rescan_requested = True
            self._wake_locked()

    def stop(self) -> None:
        """Stop the background monitoring thread and close all opened input devices."""
        thread: Optional[threading.Thread] = None
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._navigation_mode = False
            self._unmute_active_device_locked()
            self._nav_device_key = None
            self._rescan_requested = False
            thread = self._thread
            self._thread = None
            self._wake_locked()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        with self._lock:
            self._close_all_devices_locked()
            self._close_wakeup_pipe_locked()
            self._states.clear()
        logger.debug("Controller shortcut monitor stopped")

    def set_navigation_mode(self, enabled: bool) -> None:
        """Toggle overlay navigation, releasing the reserved controller when disabled."""
        with self._lock:
            enabled = bool(enabled)
            if not enabled:
                self._nav_device_key = None
            if self._navigation_mode == enabled:
                return
            self._navigation_mode = enabled
            for state in self._states.values():
                state.stick_x_dir = 0
                state.hat_x_dir = 0
            self._unmute_active_device_locked()
            if enabled:
                self._nav_enabled_at = self._clock()
                if self._nav_device_key is not None:
                    self._set_device_sandbox_muted_locked(self._nav_device_key, True)
                    self._muted_device_key = self._nav_device_key
            self._wake_locked()

    def _set_device_sandbox_muted_locked(self, device_key: Optional[str], muted: bool) -> None:
        if device_key is None:
            return
        device = self._devices.get(device_key)
        if device is None:
            return
        setter = getattr(device, "set_sandbox_muted", None)
        if callable(setter):
            setter(muted)

    def _unmute_active_device_locked(self) -> None:
        if self._muted_device_key is not None:
            self._set_device_sandbox_muted_locked(self._muted_device_key, False)
            self._muted_device_key = None

    def _is_nav_owner_locked(self, device_key: str) -> bool:
        return self._nav_device_key is None or device_key == self._nav_device_key

    def register_device_state(
        self,
        device_key: str,
        *,
        abs_x_min: int = -32768,
        abs_x_max: int = 32767,
    ) -> None:
        """Register or update per-device state (also useful in deterministic tests)."""
        with self._lock:
            state = self._states.get(device_key)
            if state is None:
                self._states[device_key] = _DeviceState(abs_x_min=abs_x_min, abs_x_max=abs_x_max)
            else:
                state.abs_x_min = abs_x_min
                state.abs_x_max = abs_x_max

    def process_event(
        self,
        device_key: str,
        ev_type: int,
        code: int,
        value: int,
        now: Optional[float] = None,
    ) -> Optional[str]:
        """Process a single evdev event and return any emitted navigation action."""
        timestamp = self._clock() if now is None else now
        nav_action: Optional[str] = None
        triggered = False

        with self._lock:
            state = self._states.setdefault(device_key, _DeviceState())

            if ev_type == EV_KEY:
                pressed = value != 0
                is_press_edge = value == 1
                was_combo_pressed = state.home_held and state.l3_held

                if code in HOME_CODES:
                    state.home_held = pressed
                elif code == BTN_THUMBL:
                    state.l3_held = pressed

                if (
                    is_press_edge
                    and not was_combo_pressed
                    and state.home_held
                    and state.l3_held
                    and not self._navigation_mode
                    and self._nav_device_key is None
                ):
                    # Reserve the controller while the GTK thread opens the overlay.
                    self._nav_device_key = device_key
                    triggered = True

                if self._navigation_mode and is_press_edge and self._is_nav_owner_locked(device_key):
                    if code in DPAD_LEFT_CODES:
                        nav_action = "left"
                    elif code in DPAD_RIGHT_CODES:
                        nav_action = "right"
                    elif self._can_accept_nav_button_locked(state, timestamp):
                        if code in CONFIRM_CODES:
                            nav_action = "confirm"
                        elif code in CANCEL_CODES:
                            nav_action = "cancel"

            elif ev_type == EV_ABS and self._navigation_mode and self._is_nav_owner_locked(device_key):
                if code == ABS_HAT0X:
                    direction = -1 if value < 0 else (1 if value > 0 else 0)
                    if direction != state.hat_x_dir:
                        state.hat_x_dir = direction
                        if direction < 0:
                            nav_action = "left"
                        elif direction > 0:
                            nav_action = "right"
                elif code == ABS_X:
                    normalized = _normalize_axis(value, state.abs_x_min, state.abs_x_max)
                    if state.stick_x_dir == 0:
                        if normalized <= -_STICK_ENGAGE_THRESHOLD:
                            state.stick_x_dir = -1
                            nav_action = "left"
                        elif normalized >= _STICK_ENGAGE_THRESHOLD:
                            state.stick_x_dir = 1
                            nav_action = "right"
                    elif abs(normalized) <= _STICK_RELEASE_THRESHOLD:
                        state.stick_x_dir = 0

        if triggered:
            try:
                self._on_trigger()
            except Exception:
                self.set_navigation_mode(False)
                logger.exception("Error invoking controller exit shortcut callback")

        if nav_action is not None and self._on_navigate is not None:
            try:
                self._on_navigate(nav_action)
            except Exception:
                logger.exception("Error dispatching controller navigation action '%s'", nav_action)

        return nav_action

    def _can_accept_nav_button_locked(self, state: _DeviceState, now: float) -> bool:
        if state.home_held or state.l3_held:
            return False
        return (now - self._nav_enabled_at) >= self._nav_grace_seconds

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

    def _close_wakeup_pipe_locked(self) -> None:
        for attr in ("_wake_r", "_wake_w"):
            fd = getattr(self, attr)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, attr, None)

    def _close_all_devices_locked(self) -> None:
        for device in self._devices.values():
            try:
                device.close()
            except Exception:
                pass
        self._devices.clear()

    def _enumerate_paths(self) -> list[str]:
        if self._device_enumerator is not None:
            return list(self._device_enumerator())
        if evdev is None:
            return []
        try:
            return list(evdev.list_devices())
        except OSError:
            return []

    def _enumerate_bridge_sockets(self) -> list[str]:
        if self._bridge_socket_enumerator is None:
            return []
        try:
            return list(self._bridge_socket_enumerator())
        except Exception:
            logger.debug("Error enumerating input bridge sockets", exc_info=True)
            return []

    def _open_device(self, path: str) -> Optional[Any]:
        if path.startswith(_BRIDGE_KEY_PREFIX):
            sock_path = Path(path[len(_BRIDGE_KEY_PREFIX) :])
            return _BridgeSocketDevice.connect(sock_path)

        opener = self._device_opener
        if opener is None:
            if evdev is None:
                return None
            opener = evdev.InputDevice
        try:
            device = opener(path)
        except OSError:
            return None

        try:
            name = str(getattr(device, "name", "") or "")
            if _is_ignored_device_name(name):
                device.close()
                return None
            capabilities = device.capabilities(verbose=False)
            if not _is_gamepad_capabilities(capabilities):
                device.close()
                return None
            return device
        except Exception:
            try:
                device.close()
            except Exception:
                pass
            return None

    def _read_abs_x_range(self, device: Any) -> tuple[int, int]:
        try:
            absinfo = device.absinfo(ABS_X)
            if absinfo is not None and absinfo.max > absinfo.min:
                return int(absinfo.min), int(absinfo.max)
        except Exception:
            pass
        return -32768, 32767

    def _sync_devices(self, selector: selectors.BaseSelector) -> None:
        discovered = set(self._enumerate_paths())
        for sock_path in self._enumerate_bridge_sockets():
            discovered.add(f"{_BRIDGE_KEY_PREFIX}{sock_path}")

        with self._lock:
            existing_paths = set(self._devices.keys())

        for stale in existing_paths - discovered:
            self._remove_device(selector, stale)

        for path in sorted(discovered - existing_paths):
            device = self._open_device(path)
            if device is None:
                continue
            abs_min, abs_max = self._read_abs_x_range(device)
            try:
                selector.register(device.fd, selectors.EVENT_READ, data=path)
            except (KeyError, ValueError, OSError):
                try:
                    device.close()
                except Exception:
                    pass
                continue
            with self._lock:
                if not self._running:
                    try:
                        selector.unregister(device.fd)
                    except (KeyError, ValueError):
                        pass
                    try:
                        device.close()
                    except Exception:
                        pass
                    return
                self._devices[path] = device
                self._states[path] = _DeviceState(abs_x_min=abs_min, abs_x_max=abs_max)
                logger.debug(
                    "Shortcut monitor attached gamepad %s (%s)",
                    path,
                    getattr(device, "name", ""),
                )

    def _remove_device(self, selector: selectors.BaseSelector, path: str) -> None:
        with self._lock:
            device = self._devices.pop(path, None)
            self._states.pop(path, None)
            if self._muted_device_key == path:
                self._muted_device_key = None
        if device is None:
            return
        try:
            selector.unregister(device.fd)
        except (KeyError, ValueError):
            pass
        try:
            device.close()
        except Exception:
            pass
        logger.debug("Shortcut monitor detached gamepad %s", path)

    def _run_loop(self) -> None:
        selector = selectors.DefaultSelector()
        try:
            with self._lock:
                wake_r = self._wake_r
            if wake_r is not None:
                selector.register(wake_r, selectors.EVENT_READ, data=None)

            next_rescan_at = 0.0

            while True:
                with self._lock:
                    if not self._running:
                        break
                    if self._rescan_requested:
                        self._rescan_requested = False
                        next_rescan_at = 0.0
                now = self._clock()
                if now >= next_rescan_at:
                    self._sync_devices(selector)
                    now = self._clock()
                    next_rescan_at = now + self._rescan_interval

                with self._lock:
                    if not self._running:
                        break

                timeout = max(0.05, min(0.5, next_rescan_at - now))
                try:
                    ready = selector.select(timeout=timeout)
                except OSError as exc:
                    if exc.errno == errno.EINTR:
                        continue
                    logger.debug("Shortcut monitor selector stopped: %s", exc)
                    break

                for key, _events in ready:
                    path = key.data
                    if path is None:
                        self._drain_wakeup()
                        continue
                    self._read_device_events(selector, path)
        finally:
            selector.close()
            with self._lock:
                self._close_all_devices_locked()

    def _read_device_events(self, selector: selectors.BaseSelector, path: str) -> None:
        with self._lock:
            device = self._devices.get(path)
        if device is None:
            return
        try:
            for event in device.read():
                self.process_event(path, event.type, event.code, event.value, self._clock())
        except BlockingIOError:
            return
        except OSError:
            self._remove_device(selector, path)
