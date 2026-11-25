"""Tests for the controller exit shortcut, confirmation overlay, and CTA button casing."""

from __future__ import annotations

import os
import socket
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk  # noqa: E402

from src.core.i18n import (  # noqa: E402
    LANGUAGE_EN,
    LANGUAGE_PT_BR,
    TRANSLATIONS,
    set_language,
)
from src.gui.presenters.main_presenter import MainPresenter  # noqa: E402
from src.gui.widgets.player_row import (  # noqa: E402
    INSTANCE_IDLE,
    INSTANCE_RUNNING,
    INSTANCE_STARTING,
    INSTANCE_STOPPING,
)
from src.gui.windows.end_session_overlay import (  # noqa: E402
    OVERLAY_WINDOW_TITLES,
    EndSessionOverlay,
)
from src.services.shortcut_monitor import (  # noqa: E402
    ABS_HAT0X,
    ABS_X,
    BTN_DPAD_LEFT,
    BTN_DPAD_RIGHT,
    BTN_EAST,
    BTN_MODE,
    BTN_SELECT,
    BTN_SOUTH,
    EV_ABS,
    EV_KEY,
    KEY_BACK,
    KEY_HOMEPAGE,
    ControllerShortcutMonitor,
    _is_gamepad_capabilities,
    _is_ignored_device_name,
)


class _FakeClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _FakePipeDevice:
    """Pipe-backed fake evdev InputDevice for exercising the real selector loop."""

    def __init__(self, name: str = "Xbox Wireless Controller") -> None:
        self.name = name
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)
        os.set_blocking(self._w, False)
        self._queue: list[SimpleNamespace] = []
        self._lock = threading.Lock()
        self.closed = False

    @property
    def fd(self) -> int:
        return self._r

    def capabilities(self, verbose: bool = False):
        return {EV_KEY: [BTN_SOUTH, BTN_EAST, BTN_SELECT, BTN_MODE]}

    def absinfo(self, code: int):
        return SimpleNamespace(min=-32768, max=32767)

    def push_event(self, ev_type: int, code: int, value: int) -> None:
        with self._lock:
            self._queue.append(SimpleNamespace(type=ev_type, code=code, value=value))
        os.write(self._w, b"x")

    def read(self):
        try:
            os.read(self._r, 64)
        except BlockingIOError:
            pass
        with self._lock:
            events = list(self._queue)
            self._queue.clear()
        return events

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for fd in (self._r, self._w):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.fixture
def gtk_display():
    """Ensure a GTK display is available and reset language after the test."""
    display = Gdk.Display.get_default()
    if display is None:
        pytest.skip("GTK display unavailable")
    set_language(LANGUAGE_EN)
    yield display
    set_language(LANGUAGE_EN)


def test_hold_home_and_select_for_two_seconds_triggers_once():
    """Holding HOME + SELECT for 2 seconds fires exactly once until released."""
    clock = _FakeClock()
    triggered = []
    monitor = ControllerShortcutMonitor(on_trigger=lambda: triggered.append(clock.now), hold_seconds=2.0, clock=clock)

    monitor.process_event("pad0", EV_KEY, BTN_MODE, 1, clock.now)
    clock.advance(0.5)
    monitor.process_event("pad0", EV_KEY, BTN_SELECT, 1, clock.now)

    # 1.99s after both buttons are held: still too early.
    assert not monitor.check_holds(clock.advance(1.99))
    assert triggered == []

    # Reaching 2.0s triggers even with no additional evdev events.
    assert monitor.check_holds(clock.advance(0.02))
    assert len(triggered) == 1

    # Continuing to hold must not double-trigger.
    assert not monitor.check_holds(clock.advance(3.0))
    assert len(triggered) == 1

    # Releasing one button unlatches so a fresh 2s hold can trigger again.
    monitor.process_event("pad0", EV_KEY, BTN_SELECT, 0, clock.advance(0.1))
    monitor.process_event("pad0", EV_KEY, BTN_SELECT, 1, clock.advance(0.1))
    assert not monitor.check_holds(clock.advance(1.5))
    assert monitor.check_holds(clock.advance(0.6))
    assert len(triggered) == 2


def test_early_release_cancels_shortcut_hold():
    """Releasing either HOME or SELECT before 2 seconds must not trigger."""
    clock = _FakeClock()
    triggered = []
    monitor = ControllerShortcutMonitor(on_trigger=lambda: triggered.append(True), hold_seconds=2.0, clock=clock)

    monitor.process_event("pad0", EV_KEY, BTN_MODE, 1, clock.now)
    monitor.process_event("pad0", EV_KEY, BTN_SELECT, 1, clock.now)
    assert not monitor.check_holds(clock.advance(1.5))

    monitor.process_event("pad0", EV_KEY, BTN_MODE, 0, clock.now)
    assert not monitor.check_holds(clock.advance(2.0))
    assert triggered == []


def test_combo_must_come_from_same_controller_and_supports_dinput_codes():
    """Cross-controller presses never combine, while D-Input KEY_HOMEPAGE + KEY_BACK work."""
    clock = _FakeClock()
    triggered = []
    monitor = ControllerShortcutMonitor(on_trigger=lambda: triggered.append(True), hold_seconds=2.0, clock=clock)

    monitor.process_event("pad0", EV_KEY, BTN_MODE, 1, clock.now)
    monitor.process_event("pad1", EV_KEY, BTN_SELECT, 1, clock.now)
    assert not monitor.check_holds(clock.advance(3.0))
    assert triggered == []

    monitor.process_event("pad2", EV_KEY, KEY_HOMEPAGE, 1, clock.now)
    monitor.process_event("pad2", EV_KEY, KEY_BACK, 1, clock.now)
    assert monitor.check_holds(clock.advance(2.0))
    assert triggered == [True]


def test_navigation_mode_routes_dpad_hat_stick_and_guards_accidental_confirm():
    """Navigation mode emits directional/confirm/cancel actions safely with stick hysteresis."""
    clock = _FakeClock()
    triggered = []
    actions = []
    monitor = ControllerShortcutMonitor(
        on_trigger=lambda: triggered.append(True),
        on_navigate=actions.append,
        hold_seconds=2.0,
        nav_grace_seconds=0.35,
        clock=clock,
    )
    monitor.register_device_state("pad0", abs_x_min=-32768, abs_x_max=32767)
    monitor.register_device_state("dualsense", abs_x_min=0, abs_x_max=255)

    # Triggering hold opens navigation mode while HOME+SELECT are still held.
    monitor.process_event("pad0", EV_KEY, BTN_MODE, 1, clock.now)
    monitor.process_event("pad0", EV_KEY, BTN_SELECT, 1, clock.now)
    assert monitor.check_holds(clock.advance(2.0))
    monitor.set_navigation_mode(True)

    # Confirm/cancel ignored during grace period or while HOME/SELECT remain held.
    monitor.process_event("pad0", EV_KEY, BTN_SOUTH, 1, clock.advance(0.1))
    monitor.process_event("pad0", EV_KEY, BTN_EAST, 1, clock.advance(0.5))
    assert actions == []

    # Release HOME+SELECT; after grace period confirm/cancel work.
    monitor.process_event("pad0", EV_KEY, BTN_MODE, 0, clock.now)
    monitor.process_event("pad0", EV_KEY, BTN_SELECT, 0, clock.now)

    # D-Pad buttons & hat axis.
    monitor.process_event("pad0", EV_KEY, BTN_DPAD_RIGHT, 1, clock.now)
    monitor.process_event("pad0", EV_KEY, BTN_DPAD_LEFT, 1, clock.now)
    monitor.process_event("pad0", EV_ABS, ABS_HAT0X, 1, clock.now)
    monitor.process_event("pad0", EV_ABS, ABS_HAT0X, 1, clock.now)  # duplicate hat value ignored
    monitor.process_event("pad0", EV_ABS, ABS_HAT0X, 0, clock.now)
    monitor.process_event("pad0", EV_ABS, ABS_HAT0X, -1, clock.now)

    # Signed stick (Xbox) hysteresis.
    monitor.process_event("pad0", EV_ABS, ABS_X, 28000, clock.now)
    monitor.process_event("pad0", EV_ABS, ABS_X, 30000, clock.now)  # still latched
    monitor.process_event("pad0", EV_ABS, ABS_X, 0, clock.now)  # returned to center
    monitor.process_event("pad0", EV_ABS, ABS_X, -28000, clock.now)

    # Events from a different controller (dualsense) are completely ignored while pad0 owns the overlay.
    assert monitor.active_navigation_device == "pad0"
    monitor.process_event("dualsense", EV_ABS, ABS_X, 240, clock.now)
    monitor.process_event("dualsense", EV_KEY, BTN_DPAD_RIGHT, 1, clock.now)
    monitor.process_event("dualsense", EV_KEY, BTN_SOUTH, 1, clock.now)
    monitor.process_event("dualsense", EV_KEY, BTN_EAST, 1, clock.now)

    monitor.process_event("pad0", EV_KEY, BTN_SOUTH, 1, clock.now)
    monitor.process_event("pad0", EV_KEY, BTN_EAST, 1, clock.now)

    assert actions == [
        "right",
        "left",
        "right",
        "left",
        "right",
        "left",
        "confirm",
        "cancel",
    ]

    # Closing navigation mode unlocks ownership; triggering from dualsense locks onto dualsense (0..255 stick).
    monitor.set_navigation_mode(False)
    assert monitor.active_navigation_device is None
    actions.clear()
    monitor.process_event("dualsense", EV_KEY, BTN_MODE, 1, clock.now)
    monitor.process_event("dualsense", EV_KEY, BTN_SELECT, 1, clock.now)
    assert monitor.check_holds(clock.advance(2.0))
    monitor.set_navigation_mode(True)
    assert monitor.active_navigation_device == "dualsense"
    monitor.process_event("dualsense", EV_KEY, BTN_MODE, 0, clock.advance(0.5))
    monitor.process_event("dualsense", EV_KEY, BTN_SELECT, 0, clock.now)

    # pad0 is now ignored while dualsense owns the overlay.
    monitor.process_event("pad0", EV_KEY, BTN_DPAD_RIGHT, 1, clock.now)
    monitor.process_event("pad0", EV_KEY, BTN_SOUTH, 1, clock.now)

    # Unsigned stick (DualSense 0..255, center ~128).
    monitor.process_event("dualsense", EV_ABS, ABS_X, 240, clock.now)
    monitor.process_event("dualsense", EV_ABS, ABS_X, 128, clock.now)
    monitor.process_event("dualsense", EV_ABS, ABS_X, 10, clock.now)
    assert actions == ["right", "left"]


def test_device_filtering_skips_virtual_twinverse_and_steam_pads():
    """Virtual Twinverse / Steam gamepads and keyboards are excluded from shortcut monitoring."""
    assert _is_ignored_device_name("Virtual Joystick by Twinverse")
    assert _is_ignored_device_name("Steam Virtual Gamepad")
    assert not _is_ignored_device_name("Sony Interactive Entertainment DualSense Wireless Controller")

    assert _is_gamepad_capabilities({EV_KEY: [BTN_SOUTH, BTN_MODE, BTN_SELECT]})
    assert _is_gamepad_capabilities({EV_KEY: [KEY_HOMEPAGE, KEY_BACK]})
    assert not _is_gamepad_capabilities({EV_KEY: [30, 31, 32]})  # regular keyboard keys only


def test_background_monitor_thread_triggers_on_real_selector_loop():
    """The background selector thread wakes on evdev events and fires after the hold duration."""
    fake_device = _FakePipeDevice()
    fired = threading.Event()
    nav_events: list[str] = []
    nav_done = threading.Event()

    def on_nav(action: str) -> None:
        nav_events.append(action)
        if action == "right":
            nav_done.set()

    monitor = ControllerShortcutMonitor(
        on_trigger=fired.set,
        on_navigate=on_nav,
        hold_seconds=0.15,
        rescan_interval=0.2,
        nav_grace_seconds=0.0,
        device_enumerator=lambda: ["/dev/input/event99"],
        device_opener=lambda _path: fake_device,
    )
    try:
        monitor.start()
        assert monitor.is_running
        time.sleep(0.05)
        fake_device.push_event(EV_KEY, BTN_MODE, 1)
        fake_device.push_event(EV_KEY, BTN_SELECT, 1)
        assert fired.wait(timeout=1.5)

        monitor.set_navigation_mode(True)
        fake_device.push_event(EV_KEY, BTN_DPAD_RIGHT, 1)
        assert nav_done.wait(timeout=1.0)
        assert nav_events == ["right"]
    finally:
        monitor.stop()
        assert not monitor.is_running
        assert fake_device.closed


def test_shortcut_monitor_reads_bridge_socket_when_controller_is_exclusively_grabbed(tmp_path):
    """Shortcut monitor receives HOME+SELECT and stick navigation via tw_event3000.sock when EVIOCGRAB hides evdev."""
    sock_dir = tmp_path / "instance_1" / ".tw-in" / "sock"
    sock_dir.mkdir(parents=True)
    sock_path = sock_dir / "tw_event3000.sock"
    desc_path = sock_dir / "tw_event3000.desc"

    # Build a valid UdynDesc with unsigned DualSense ABS_X [0, 255] and 24-byte 64-bit input_event records.
    desc = bytearray(1752)
    struct.pack_into("<II", desc, 0, 0x54575549, 1)
    struct.pack_into("<iiiiii", desc, 212, 128, 0, 255, 0, 0, 0)
    struct.pack_into("<I", desc, 1748, 24)
    desc_path.write_bytes(desc)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)
    server.settimeout(2.0)

    fired = threading.Event()
    nav_events: list[str] = []
    nav_done = threading.Event()

    def on_nav(action: str) -> None:
        nav_events.append(action)
        if len(nav_events) >= 2:
            nav_done.set()

    monitor = ControllerShortcutMonitor(
        on_trigger=fired.set,
        on_navigate=on_nav,
        hold_seconds=0.15,
        rescan_interval=0.2,
        nav_grace_seconds=0.0,
        device_enumerator=lambda: [],
        bridge_socket_enumerator=lambda: [str(sock_path)],
    )
    conn = None
    try:
        monitor.start()
        conn, _ = server.accept()

        # Send HOME + SELECT across a split chunk boundary to exercise partial-frame buffering.
        frame_home = struct.pack("<qqHHi", 1, 0, EV_KEY, BTN_MODE, 1)
        frame_select = struct.pack("<qqHHi", 1, 1000, EV_KEY, BTN_SELECT, 1)
        conn.sendall(frame_home[:10])
        time.sleep(0.02)
        conn.sendall(frame_home[10:] + frame_select)
        assert fired.wait(timeout=1.5)

        monitor.set_navigation_mode(True)
        conn.sendall(
            struct.pack("<qqHHi", 2, 0, EV_KEY, BTN_MODE, 0)
            + struct.pack("<qqHHi", 2, 100, EV_KEY, BTN_SELECT, 0)
            + struct.pack("<qqHHi", 2, 200, EV_ABS, ABS_X, 245)
            + struct.pack("<qqHHi", 2, 300, EV_KEY, BTN_SOUTH, 1)
        )
        assert nav_done.wait(timeout=1.5)
        assert nav_events == ["right", "confirm"]

        # Verify TWCTL handshake: monitor registered on connect, muted on nav=True, unmuted on nav=False.
        monitor.set_navigation_mode(False)
        conn.settimeout(1.0)
        ctl = b""
        while len(ctl) < 24:
            chunk = conn.recv(24 - len(ctl))
            if not chunk:
                break
            ctl += chunk
        assert ctl == b"TWCTL\x01\x00\x00TWCTL\x02\x01\x00TWCTL\x02\x00\x00"
    finally:
        if conn is not None:
            conn.close()
        server.close()
        monitor.stop()


def test_shortcut_monitor_mutes_only_triggering_bridge_and_ignores_other_player_bridge(tmp_path):
    """Only the bridge controller that triggered HOME+SELECT gets muted and controls the End Session overlay."""

    def make_bridge_socket(instance_name: str):
        sock_dir = tmp_path / instance_name / ".tw-in" / "sock"
        sock_dir.mkdir(parents=True)
        sock_path = sock_dir / "tw_event3000.sock"
        desc_path = sock_dir / "tw_event3000.desc"
        desc = bytearray(1752)
        struct.pack_into("<II", desc, 0, 0x54575549, 1)
        struct.pack_into("<iiiiii", desc, 212, 0, -32768, 32767, 0, 0, 0)
        struct.pack_into("<I", desc, 1748, 24)
        desc_path.write_bytes(desc)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(4)
        srv.settimeout(2.0)
        return sock_path, srv

    sock1, srv1 = make_bridge_socket("instance_1")
    sock2, srv2 = make_bridge_socket("instance_2")

    fired = threading.Event()
    nav_events: list[str] = []
    nav_done = threading.Event()

    def on_nav(action: str) -> None:
        nav_events.append(action)
        if action == "confirm":
            nav_done.set()

    monitor = ControllerShortcutMonitor(
        on_trigger=fired.set,
        on_navigate=on_nav,
        hold_seconds=0.15,
        rescan_interval=0.2,
        nav_grace_seconds=0.0,
        device_enumerator=lambda: [],
        bridge_socket_enumerator=lambda: [str(sock1), str(sock2)],
    )
    conn1 = conn2 = None
    try:
        monitor.start()
        conn1, _ = srv1.accept()
        conn2, _ = srv2.accept()
        conn1.settimeout(1.0)
        conn2.settimeout(1.0)
        assert conn1.recv(8) == b"TWCTL\x01\x00\x00"
        assert conn2.recv(8) == b"TWCTL\x01\x00\x00"

        # Player 1 triggers HOME + SELECT.
        conn1.sendall(
            struct.pack("<qqHHi", 1, 0, EV_KEY, BTN_MODE, 1) + struct.pack("<qqHHi", 1, 100, EV_KEY, BTN_SELECT, 1)
        )
        assert fired.wait(timeout=1.5)

        # Entering navigation mode mutes Player 1's bridge ONLY.
        monitor.set_navigation_mode(True)
        assert conn1.recv(8) == b"TWCTL\x02\x01\x00"
        conn2.settimeout(0.1)
        with pytest.raises(socket.timeout):
            conn2.recv(8)

        # Player 2's navigation/confirm inputs are ignored; Player 1's inputs work.
        conn2.sendall(
            struct.pack("<qqHHi", 2, 0, EV_KEY, BTN_DPAD_RIGHT, 1) + struct.pack("<qqHHi", 2, 100, EV_KEY, BTN_SOUTH, 1)
        )
        time.sleep(0.05)
        assert nav_events == []

        conn1.sendall(
            struct.pack("<qqHHi", 3, 0, EV_KEY, BTN_MODE, 0)
            + struct.pack("<qqHHi", 3, 100, EV_KEY, BTN_SELECT, 0)
            + struct.pack("<qqHHi", 3, 200, EV_KEY, BTN_DPAD_RIGHT, 1)
            + struct.pack("<qqHHi", 3, 300, EV_KEY, BTN_SOUTH, 1)
        )
        assert nav_done.wait(timeout=1.5)
        assert nav_events == ["right", "confirm"]

        # Exiting navigation mode unmutes Player 1's bridge.
        monitor.set_navigation_mode(False)
        assert conn1.recv(8) == b"TWCTL\x02\x00\x00"
    finally:
        for conn in (conn1, conn2):
            if conn is not None:
                conn.close()
        srv1.close()
        srv2.close()
        monitor.stop()


def test_end_session_overlay_defaults_to_cancel_and_supports_navigation_and_i18n(gtk_display):
    """Verify EndSessionOverlay defaults to Cancel, responds to gamepad navigation, and translates live."""
    app = Adw.Application(application_id="io.github.mall0r.Twinverse.test.exit_overlay")

    confirmed = []
    cancelled = []
    overlay = EndSessionOverlay(
        app,
        on_confirm=lambda: confirmed.append(True),
        on_cancel=lambda: cancelled.append(True),
    )
    assert overlay.get_title() in OVERLAY_WINDOW_TITLES
    assert overlay.selected_option == "cancel"
    assert overlay.cancel_button.get_label() == "Cancel"
    assert overlay.confirm_button.get_label() == "End Session"
    assert "is-selected" in overlay.cancel_button.get_css_classes()
    assert "is-selected" not in overlay.confirm_button.get_css_classes()

    set_language(LANGUAGE_PT_BR)
    assert overlay.get_title() in OVERLAY_WINDOW_TITLES
    assert overlay.cancel_button.get_label() == "Cancelar"
    assert overlay.confirm_button.get_label() == "Encerrar"

    # Navigating right selects Confirm; navigating left returns to Cancel.
    overlay.navigate("right")
    assert overlay.selected_option == "confirm"
    assert "is-selected" in overlay.confirm_button.get_css_classes()

    overlay.navigate("left")
    assert overlay.selected_option == "cancel"

    # Confirming while Cancel is selected cancels without stopping the session.
    overlay.navigate("confirm")
    assert confirmed == []
    assert cancelled == [True]

    # Opening again and navigating Right + Confirm triggers on_confirm once.
    confirmed2 = []
    cancelled2 = []
    overlay2 = EndSessionOverlay(
        app,
        on_confirm=lambda: confirmed2.append(True),
        on_cancel=lambda: cancelled2.append(True),
    )
    overlay2.navigate("right")
    overlay2.navigate("confirm")
    overlay2.navigate("confirm")  # idempotent after resolve
    assert confirmed2 == [True]
    assert cancelled2 == []


def test_main_presenter_wires_shortcut_monitor_and_confirmation_flow(gtk_display, monkeypatch):
    """Verify MainPresenter starts/stops the shortcut monitor with instances and confirms session stop."""
    presenter = MainPresenter.__new__(MainPresenter)
    presenter._app = Adw.Application(application_id="io.github.mall0r.Twinverse.test.presenter_exit")
    presenter._instance_states = {}
    presenter._starting_instances = set()
    presenter._owned_instances = set()
    presenter._progress_shown = {}
    presenter._minimize_after_launch = False
    presenter._bulk_operation_in_progress = False
    presenter._exit_overlay = None
    presenter._shortcut_monitor = Mock()
    presenter._launch_controller = Mock()
    presenter.window = Mock()
    layout_page = Mock()
    layout_page.player_rows = []
    presenter.window.get_layout_page.return_value = layout_page

    # Starting an instance activates the controller shortcut monitor.
    presenter._set_instance_state(0, INSTANCE_STARTING)
    presenter._shortcut_monitor.start.assert_called_once()

    presenter._set_instance_state(0, INSTANCE_RUNNING)
    presenter._on_exit_shortcut_triggered()
    assert presenter._exit_overlay is not None
    presenter._shortcut_monitor.set_navigation_mode.assert_called_with(True)

    # Cancelling closes overlay and keeps the session running.
    presenter._on_exit_shortcut_navigation("cancel")
    assert presenter._exit_overlay is None
    presenter._shortcut_monitor.set_navigation_mode.assert_called_with(False)
    presenter._launch_controller.stop_instances.assert_not_called()

    # Triggering again and selecting Right + Confirm ends the session and restores MainWindow.
    presenter._on_exit_shortcut_triggered()
    presenter._on_exit_shortcut_navigation("right")
    presenter._on_exit_shortcut_navigation("confirm")
    assert presenter._exit_overlay is None
    presenter._launch_controller.stop_instances.assert_called_once()
    presenter.window.present.assert_called_once()
    assert presenter._instance_states[0] == INSTANCE_STOPPING

    # Returning to idle stops the background monitor.
    presenter._set_instance_state(0, INSTANCE_IDLE)
    presenter._shortcut_monitor.stop.assert_called_once()


def test_all_cta_buttons_use_title_case_in_every_language():
    """Every CTA button label must capitalize the first letter of every word in both EN and PT-BR."""
    cta_keys = (
        "common.ok",
        "common.cancel",
        "session.launch_button",
        "session.end_button",
        "session.starting_button",
        "session.stopping_button",
        "exit_confirm.confirm",
        "exit_confirm.cancel",
        "roster.add_player",
        "player.env_add",
        "player.action.stop",
        "player.action.cancel",
        "player.action.stopping",
        "player.action.start",
        "player.action.install",
        "prefs.reset.button",
        "prefs.instances.confirm_reset",
    )
    for lang, catalog in TRANSLATIONS.items():
        for key in cta_keys:
            label = catalog[key]
            words = label.split()
            assert words, f"{lang}:{key} must not be empty"
            for word in words:
                assert word[0].isupper(), f"CTA button {lang}:{key} = {label!r} has lowercase word {word!r}"
