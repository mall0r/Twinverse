"""Background gamepad monitor for the global session-exit shortcut (HOME + SELECT)."""

from __future__ import annotations

import errno
import logging
import os
import selectors
import threading
import time
from dataclasses import dataclass
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
BTN_SELECT = 314  # Select / View / Share / Minus
BTN_MODE = 316  # Home / Guide / PS / Steam
BTN_DPAD_LEFT = 546
BTN_DPAD_RIGHT = 547

KEY_BACK = 158  # Select on some D-Input / Android controllers
KEY_HOMEPAGE = 172  # Home on some D-Input / Android controllers

ABS_X = 0
ABS_HAT0X = 16

HOME_CODES = frozenset({BTN_MODE, KEY_HOMEPAGE})
SELECT_CODES = frozenset({BTN_SELECT, KEY_BACK})
CONFIRM_CODES = frozenset({BTN_SOUTH})
CANCEL_CODES = frozenset({BTN_EAST})
DPAD_LEFT_CODES = frozenset({BTN_DPAD_LEFT})
DPAD_RIGHT_CODES = frozenset({BTN_DPAD_RIGHT})

_IGNORED_DEVICE_SUBSTRINGS = (
    "twinverse",
    "steam virtual gamepad",
)

DEFAULT_HOLD_SECONDS = 2.0
DEFAULT_RESCAN_INTERVAL = 1.5
DEFAULT_NAV_GRACE_SECONDS = 0.35
_STICK_ENGAGE_THRESHOLD = 0.6
_STICK_RELEASE_THRESHOLD = 0.35


@dataclass
class _DeviceState:
    """Tracked button and axis state for one physical gamepad."""

    home_held: bool = False
    select_held: bool = False
    combo_since: Optional[float] = None
    combo_triggered: bool = False
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
    return bool(keys & HOME_CODES) and bool(keys & SELECT_CODES)


def _normalize_axis(value: int, axis_min: int, axis_max: int) -> float:
    """Normalize a raw ABS_X reading into [-1.0, 1.0]."""
    span = axis_max - axis_min
    if span <= 0:
        return 0.0
    midpoint = (axis_max + axis_min) / 2.0
    half_span = span / 2.0
    normalized = (value - midpoint) / half_span
    return max(-1.0, min(1.0, normalized))


class ControllerShortcutMonitor:
    """Watch connected gamepads for a 2-second HOME + SELECT hold and modal navigation."""

    def __init__(
        self,
        on_trigger: Callable[[], None],
        on_navigate: Optional[Callable[[str], None]] = None,
        *,
        hold_seconds: float = DEFAULT_HOLD_SECONDS,
        rescan_interval: float = DEFAULT_RESCAN_INTERVAL,
        nav_grace_seconds: float = DEFAULT_NAV_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        device_enumerator: Optional[Callable[[], list[str]]] = None,
        device_opener: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Initialize the shortcut monitor without starting its background thread."""
        self._on_trigger = on_trigger
        self._on_navigate = on_navigate
        self._hold_seconds = max(0.1, float(hold_seconds))
        self._rescan_interval = max(0.2, float(rescan_interval))
        self._nav_grace_seconds = max(0.0, float(nav_grace_seconds))
        self._clock = clock
        self._device_enumerator = device_enumerator
        self._device_opener = device_opener

        self._lock = threading.RLock()
        self._running = False
        self._navigation_mode = False
        self._nav_enabled_at = 0.0
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

    def start(self) -> None:
        """Start monitoring connected gamepads in a daemon thread."""
        with self._lock:
            if self._running:
                return
            if evdev is None and self._device_enumerator is None:
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
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name="twinverse-shortcut-monitor",
                daemon=True,
            )
            self._thread.start()
            logger.debug("Controller shortcut monitor started")

    def stop(self) -> None:
        """Stop the background monitoring thread and close all opened input devices."""
        thread: Optional[threading.Thread] = None
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._navigation_mode = False
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
        """Toggle routing of gamepad inputs to confirmation-overlay navigation."""
        with self._lock:
            enabled = bool(enabled)
            if self._navigation_mode == enabled:
                return
            self._navigation_mode = enabled
            if enabled:
                self._nav_enabled_at = self._clock()
                for state in self._states.values():
                    state.combo_since = None
                    state.stick_x_dir = 0
                    state.hat_x_dir = 0
            else:
                for state in self._states.values():
                    state.combo_since = None
                    state.stick_x_dir = 0
                    state.hat_x_dir = 0
                    if not (state.home_held and state.select_held):
                        state.combo_triggered = False
            self._wake_locked()

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

        with self._lock:
            state = self._states.setdefault(device_key, _DeviceState())

            if ev_type == EV_KEY:
                pressed = value != 0
                is_press_edge = value == 1

                if code in HOME_CODES:
                    state.home_held = pressed
                    self._update_combo_state_locked(state, timestamp)
                elif code in SELECT_CODES:
                    state.select_held = pressed
                    self._update_combo_state_locked(state, timestamp)

                if self._navigation_mode and is_press_edge:
                    if code in DPAD_LEFT_CODES:
                        nav_action = "left"
                    elif code in DPAD_RIGHT_CODES:
                        nav_action = "right"
                    elif self._can_accept_nav_button_locked(state, timestamp):
                        if code in CONFIRM_CODES:
                            nav_action = "confirm"
                        elif code in CANCEL_CODES:
                            nav_action = "cancel"

            elif ev_type == EV_ABS and self._navigation_mode:
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

        if nav_action is not None and self._on_navigate is not None:
            try:
                self._on_navigate(nav_action)
            except Exception:
                logger.exception("Error dispatching controller navigation action '%s'", nav_action)

        return nav_action

    def check_holds(self, now: Optional[float] = None) -> bool:
        """Check whether any device has held HOME + SELECT long enough to trigger."""
        timestamp = self._clock() if now is None else now
        triggered = False

        with self._lock:
            if self._navigation_mode:
                return False
            for state in self._states.values():
                if (
                    state.home_held
                    and state.select_held
                    and not state.combo_triggered
                    and state.combo_since is not None
                    and (timestamp - state.combo_since) >= self._hold_seconds
                ):
                    state.combo_triggered = True
                    state.combo_since = None
                    triggered = True
                    break

        if triggered:
            try:
                self._on_trigger()
            except Exception:
                logger.exception("Error invoking controller exit shortcut callback")

        return triggered

    def _update_combo_state_locked(self, state: _DeviceState, now: float) -> None:
        if state.home_held and state.select_held:
            if not self._navigation_mode and not state.combo_triggered and state.combo_since is None:
                state.combo_since = now
        else:
            state.combo_since = None
            state.combo_triggered = False

    def _can_accept_nav_button_locked(self, state: _DeviceState, now: float) -> bool:
        if state.home_held or state.select_held:
            return False
        return (now - self._nav_enabled_at) >= self._nav_grace_seconds

    def _next_timeout_locked(self, now: float, next_rescan_at: float) -> float:
        timeout = max(0.05, min(0.5, next_rescan_at - now))
        if not self._navigation_mode:
            for state in self._states.values():
                if (
                    state.home_held
                    and state.select_held
                    and not state.combo_triggered
                    and state.combo_since is not None
                ):
                    remaining = max(0.0, self._hold_seconds - (now - state.combo_since))
                    timeout = min(timeout, remaining)
        return timeout

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

    def _open_device(self, path: str) -> Optional[Any]:
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
                now = self._clock()
                if now >= next_rescan_at:
                    self._sync_devices(selector)
                    now = self._clock()
                    next_rescan_at = now + self._rescan_interval

                self.check_holds(now)

                with self._lock:
                    if not self._running:
                        break
                    timeout = self._next_timeout_locked(now, next_rescan_at)

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

                self.check_holds(self._clock())
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
