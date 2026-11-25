"""Tests for automatic live hotplug refresh of input devices and displays."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk  # noqa: E402

from src.core.i18n import LANGUAGE_EN, set_language  # noqa: E402
from src.gui.controllers.settings_controller import SettingsController  # noqa: E402
from src.gui.presenters.main_presenter import MainPresenter  # noqa: E402
from src.gui.widgets.player_row import PlayerRow  # noqa: E402
from src.services.device_hotplug import DeviceHotplugMonitor  # noqa: E402


class _FakeSignalObject:
    """Minimal GObject-like signal hub for testing display/monitor hotplug."""

    def __init__(self) -> None:
        self._next_id = 1
        self._handlers: dict[int, tuple[str, Callable[..., Any]]] = {}

    def connect(self, signal_name: str, callback) -> int:
        hid = self._next_id
        self._next_id += 1
        self._handlers[hid] = (signal_name, callback)
        return hid

    def disconnect(self, handler_id: int) -> None:
        self._handlers.pop(handler_id, None)

    def emit(self, signal_name: str, *args) -> None:
        for name, cb in list(self._handlers.values()):
            if name == signal_name:
                cb(self, *args)

    @property
    def connected_signals(self) -> list[str]:
        return [name for name, _ in self._handlers.values()]


class _FakeMonitorsModel(_FakeSignalObject):
    def __init__(self, monitors: list[_FakeSignalObject]) -> None:
        super().__init__()
        self._monitors = list(monitors)

    def get_n_items(self) -> int:
        return len(self._monitors)

    def get_item(self, index: int):
        return self._monitors[index]

    def add_monitor(self, monitor: _FakeSignalObject) -> None:
        pos = len(self._monitors)
        self._monitors.append(monitor)
        self.emit("items-changed", pos, 0, 1)

    def remove_monitor(self, monitor: _FakeSignalObject) -> None:
        pos = self._monitors.index(monitor)
        self._monitors.pop(pos)
        self.emit("items-changed", pos, 1, 0)


class _FakeDisplay:
    def __init__(self, monitors: _FakeMonitorsModel) -> None:
        self._monitors = monitors

    def get_monitors(self) -> _FakeMonitorsModel:
        return self._monitors


@pytest.fixture
def gtk_display():
    """Ensure a GTK display is available and reset language after the test."""
    display = Gdk.Display.get_default()
    if display is None:
        pytest.skip("GTK display unavailable")
    set_language(LANGUAGE_EN)
    yield display
    set_language(LANGUAGE_EN)


def test_inotify_hotplug_coalesces_burst_events_and_re_watches_subdir(tmp_path):
    """Input hotplug monitor coalesces burst node creations and auto-watches newly created by-id dirs."""
    by_id = tmp_path / "by-id"
    events: list[float] = []
    first_done = threading.Event()
    second_done = threading.Event()

    def on_change() -> None:
        events.append(time.monotonic())
        if len(events) == 1:
            first_done.set()
        elif len(events) >= 2:
            second_done.set()

    monitor = DeviceHotplugMonitor(
        on_change=on_change,
        watch_dirs=(tmp_path, by_id),
        debounce_seconds=0.08,
        watch_displays=False,
    )
    try:
        monitor.start()
        assert monitor.is_running
        time.sleep(0.03)

        # Simulate plugging a USB gamepad: create by-id dir + multiple nodes in rapid burst.
        by_id.mkdir()
        (tmp_path / "event25").write_text("")
        (by_id / "usb-Controller-event-joystick").write_text("")
        (by_id / "usb-Controller-joystick").write_text("")

        assert first_done.wait(timeout=1.5)
        time.sleep(0.15)
        assert len(events) == 1

        # Simulate unplugging the gamepad from the newly auto-watched by-id dir.
        (by_id / "usb-Controller-event-joystick").unlink()
        assert second_done.wait(timeout=1.5)
        assert len(events) == 2
    finally:
        monitor.stop()
        assert not monitor.is_running


def test_display_hotplug_reacts_to_monitor_add_remove_and_geometry_changes():
    """Display hotplug watcher responds to monitor hotplug and geometry/refresh changes and cleans up signals."""
    mon1 = _FakeSignalObject()
    mon2 = _FakeSignalObject()
    model = _FakeMonitorsModel([mon1])
    display = _FakeDisplay(model)
    changes: list[int] = []

    monitor = DeviceHotplugMonitor(
        on_change=lambda: changes.append(1),
        watch_dirs=(),
        debounce_seconds=0.0,
        watch_displays=True,
        display_provider=lambda: display,
    )
    try:
        monitor.start()
        assert set(mon1.connected_signals) == {"notify::geometry", "notify::refresh-rate"}

        # Resolution or rotation change on existing monitor triggers refresh.
        mon1.emit("notify::geometry", None)
        assert len(changes) == 1

        # Connecting a second monitor triggers refresh and attaches its property handlers.
        model.add_monitor(mon2)
        assert len(changes) == 2
        assert set(mon2.connected_signals) == {"notify::geometry", "notify::refresh-rate"}

        # Refresh rate change on the new monitor triggers refresh.
        mon2.emit("notify::refresh-rate", None)
        assert len(changes) == 3

        # Disconnecting the second monitor triggers refresh and disconnects its handlers.
        model.remove_monitor(mon2)
        assert len(changes) == 4
        assert mon2.connected_signals == []
    finally:
        monitor.stop()
        assert mon1.connected_signals == []
        assert model.connected_signals == []


def test_main_presenter_hotplug_updates_ui_only_when_devices_change():
    """Verify MainPresenter refreshes UI on hardware changes, skips identical snapshots, and stops monitor on close."""
    presenter = MainPresenter.__new__(MainPresenter)
    presenter._app = Mock()
    presenter._instance_states = {}
    presenter._starting_instances = set()
    presenter._owned_instances = set()
    presenter._progress_shown = {}
    presenter._exit_overlay = None
    presenter._shortcut_monitor = Mock()
    presenter._hotplug_monitor = Mock()
    presenter._hotplug_lock = threading.Lock()
    presenter._hotplug_refresh_pending = True
    presenter._launch_controller = Mock()
    presenter._verification_controller = Mock()
    presenter._verification_controller.get_verification_status.return_value = True
    presenter.window = Mock()
    layout_page = Mock()
    layout_page.get_selected_players.return_value = [0]
    layout_page.get_layout_error.return_value = None
    layout_page.get_data.return_value = {
        "num_players": 1,
        "mode": "splitscreen",
        "orientation": "horizontal",
        "player_configs": [],
        "selected_players": [0],
    }
    presenter.window.get_layout_page.return_value = layout_page

    initial = {
        "joystick": [],
        "mouse": [],
        "keyboard": [],
        "audio": [],
        "displays": [
            {"id": 0, "name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "refresh_rate_mhz": 60000}
        ],
    }
    updated = {
        "joystick": [{"id": "/dev/input/by-id/usb-Xbox-event-joystick", "name": "Xbox"}],
        "mouse": [],
        "keyboard": [],
        "audio": [],
        "displays": [
            {"id": 0, "name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080, "refresh_rate_mhz": 60000},
            {"id": 1, "name": "HDMI-1", "x": 1920, "y": 0, "width": 2560, "height": 1440, "refresh_rate_mhz": 144000},
        ],
    }

    presenter._last_devices_info = initial
    presenter._settings_controller = Mock()
    presenter._settings_controller.get_devices_info.return_value = initial

    # Identical snapshot must not disturb the UI.
    assert presenter._on_hotplug_devices_changed() is False
    assert presenter._hotplug_refresh_pending is False
    layout_page.update_devices_info.assert_not_called()

    # Changed snapshot (controller + second monitor) updates the layout page and launch readiness.
    presenter._settings_controller.get_devices_info.return_value = updated
    assert presenter._on_hotplug_devices_changed() is False
    layout_page.update_devices_info.assert_called_once_with(updated)
    assert presenter._last_devices_info == updated

    # Closing the window stops the hotplug monitor cleanly.
    presenter.on_close_requested()
    presenter._hotplug_monitor.stop.assert_called_once()


def test_settings_controller_get_devices_info_scans_inputs_once(monkeypatch):
    """Verify SettingsController.get_devices_info queries get_input_devices() only once per refresh."""
    device_manager = Mock()
    device_manager.get_input_devices.return_value = {
        "joystick": [{"id": "/dev/input/by-id/usb-Pad-event-joystick", "name": "Pad"}],
        "mouse": [],
        "keyboard": [],
    }
    device_manager.get_audio_devices.return_value = []
    device_manager.get_screen_info.return_value = []

    controller = SettingsController.__new__(SettingsController)
    controller._device_manager = device_manager

    info = controller.get_devices_info()
    assert len(info["joystick"]) == 1
    device_manager.get_input_devices.assert_called_once()


def test_player_row_update_devices_skips_unchanged_dropdown_models(gtk_display):
    """Updating displays alone must not replace joystick/audio models, while gamepad hotplug updates live."""
    pad = {"id": "/dev/input/by-id/usb-Pad-event-joystick", "name": "Pad"}
    devices = {"joystick": [pad], "audio": [{"id": "sink0", "name": "Speakers"}], "displays": []}
    row = PlayerRow(0, devices)
    row.joystick_row.set_selected(1)
    assert row.is_controller_connected()

    joystick_model_before = row.joystick_row.get_model()
    audio_model_before = row.audio_row.get_model()

    # Display-only change leaves joystick and audio models untouched.
    row.update_devices(
        {
            "joystick": [pad],
            "audio": [{"id": "sink0", "name": "Speakers"}],
            "displays": [{"id": 0, "name": "DP-1"}],
        }
    )
    assert row.joystick_row.get_model() is joystick_model_before
    assert row.audio_row.get_model() is audio_model_before

    # Unplugging the assigned controller marks it disconnected while keeping audio untouched.
    row.update_devices({"joystick": [], "audio": [{"id": "sink0", "name": "Speakers"}], "displays": []})
    assert row.audio_row.get_model() is audio_model_before
    assert row.has_controller_selected()
    assert not row.is_controller_connected()

    # Replugging the controller restores live connected state automatically.
    row.update_devices({"joystick": [pad], "audio": [{"id": "sink0", "name": "Speakers"}], "displays": []})
    assert row.has_controller_selected()
    assert row.is_controller_connected()
