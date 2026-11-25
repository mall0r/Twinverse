"""Behavioral coverage for the Player Setup controller dropdown list and marquee labels."""

import time

import gi
import pytest

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from src.core.i18n import (  # noqa: E402
    LANGUAGE_EN,
    LANGUAGE_PT_BR,
    get_language_preference,
    set_language,
)
from src.gui.pages.layout_settings_page import LayoutSettingsPage  # noqa: E402
from src.gui.widgets.marquee_label import (  # noqa: E402
    MarqueeLabel,
    compute_marquee_offset,
)
from src.gui.widgets.player_row import PlayerRow, _ControllerOptionRow  # noqa: E402
from src.models import PlayerInstanceConfig, Profile  # noqa: E402


def _pump_events(duration_seconds: float = 0.15) -> None:
    context = GLib.MainContext.default()
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        while context.pending():
            super(GLib.MainContext, context).iteration(False)
        time.sleep(0.01)


def _find_descendants(widget: Gtk.Widget, widget_type: type) -> list:
    found = []
    if isinstance(widget, widget_type):
        found.append(widget)
    child = widget.get_first_child()
    while child is not None:
        found.extend(_find_descendants(child, widget_type))
        child = child.get_next_sibling()
    return found


def _require_gtk_display() -> None:
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A GTK display is required")
    Adw.init()


def test_compute_marquee_offset_follows_ping_pong_cycle():
    """Offset pauses at both ends, scrolls linearly across the overflow, and wraps cleanly."""
    overflow = 100.0
    kwargs = {"pause_start": 1.0, "pause_end": 1.0, "forward_speed": 50.0, "return_speed": 100.0}
    # Forward = 2.0s, return = 1.0s, full cycle = 5.0s.
    assert compute_marquee_offset(0.0, overflow, **kwargs) == 0.0
    assert compute_marquee_offset(0.5, overflow, **kwargs) == 0.0
    assert compute_marquee_offset(2.0, overflow, **kwargs) == pytest.approx(50.0)
    assert compute_marquee_offset(3.0, overflow, **kwargs) == pytest.approx(100.0)
    assert compute_marquee_offset(3.5, overflow, **kwargs) == pytest.approx(100.0)
    assert compute_marquee_offset(4.5, overflow, **kwargs) == pytest.approx(50.0)
    assert compute_marquee_offset(5.0, overflow, **kwargs) == 0.0
    assert compute_marquee_offset(2.0, 0.0, **kwargs) == 0.0


def test_marquee_label_scrolls_only_when_text_overflows_and_respects_reduced_motion():
    """Overflowing text starts scrolling while mapped and falls back to ellipsis when animations are off."""
    _require_gtk_display()
    settings = Gtk.Settings.get_default()
    previous_animations = bool(settings.get_property("gtk-enable-animations")) if settings is not None else True

    win = Gtk.Window()
    win.set_default_size(320, 120)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    short_label = MarqueeLabel("Xbox Pad", max_width=160)
    long_label = MarqueeLabel(
        "Sony Interactive Entertainment DualSense Edge Wireless Controller USB-C Edition",
        max_width=160,
    )
    box.append(short_label)
    box.append(long_label)
    win.set_child(box)

    try:
        if settings is not None:
            settings.set_property("gtk-enable-animations", True)
        win.present()
        _pump_events(0.2)

        assert short_label.get_overflow() == 0.0
        assert not short_label.is_scrolling()

        # Natural width stays capped so long names never stretch the popup container.
        assert long_label.measure(Gtk.Orientation.HORIZONTAL, -1)[1] <= 160
        assert long_label.get_overflow() > 0.0
        assert long_label.is_scrolling()

        mid_offset = long_label.advance(2.5)
        assert mid_offset > 0.0
        assert long_label.get_scroll_offset() == pytest.approx(mid_offset)

        # Disabling animations stops scrolling and restores end ellipsization.
        if settings is not None:
            settings.set_property("gtk-enable-animations", False)
            _pump_events(0.1)
            assert not long_label.is_scrolling()
            assert long_label.get_scroll_offset() == 0.0
            assert long_label._label.get_ellipsize() == Pango.EllipsizeMode.END
    finally:
        if settings is not None:
            settings.set_property("gtk-enable-animations", previous_animations)
        win.destroy()
        _pump_events(0.05)


def test_marquee_label_damages_full_vertical_bounds_across_scroll_frames():
    """Scrolling frames cover the full widget height so partial-damage renderers leave no top-edge dots."""
    _require_gtk_display()
    settings = Gtk.Settings.get_default()
    previous_animations = bool(settings.get_property("gtk-enable-animations")) if settings is not None else True

    win = Gtk.Window()
    win.set_default_size(240, 80)
    label = MarqueeLabel(
        "Sony Interactive Entertainment DualSense Edge Wireless Controller USB-C Edition",
        max_width=160,
    )
    win.set_child(label)

    try:
        if settings is not None:
            settings.set_property("gtk-enable-animations", True)
        win.present()
        _pump_events(0.2)

        # Inner text is vertically padded so ascenders do not sit on y=0.
        assert label.get_height() >= label._label.get_height() + 4

        bounds_by_frame = []
        for elapsed in (0.0, 1.5):
            label.advance(elapsed)
            snapshot = Gtk.Snapshot()
            label.do_snapshot(snapshot)
            node = snapshot.to_node()
            assert node is not None
            rect = node.get_bounds()
            assert rect.origin.y == pytest.approx(0.0)
            assert rect.size.height == pytest.approx(float(label.get_height()))
            bounds_by_frame.append(rect.origin.x)

        assert bounds_by_frame[1] < bounds_by_frame[0]
    finally:
        if settings is not None:
            settings.set_property("gtk-enable-animations", previous_animations)
        win.destroy()
        _pump_events(0.05)


def test_controller_dropdown_marks_selected_option_with_dot_and_scrolls_long_names():
    """The open Controls dropdown marks only the active option with a dot and scrolls long names."""
    _require_gtk_display()
    settings = Gtk.Settings.get_default()
    previous_animations = bool(settings.get_property("gtk-enable-animations")) if settings is not None else True
    long_name = "Sony Interactive Entertainment DualSense Edge Wireless Controller USB-C Edition"
    devices = {
        "joystick": [
            {"id": "/dev/input/by-id/pad-1", "name": "Xbox Wireless Controller"},
            {"id": "/dev/input/by-id/pad-2", "name": "Xbox Wireless Controller"},
            {"id": "/dev/input/by-id/pad-3", "name": long_name},
        ],
        "audio": [],
    }

    win = Gtk.Window()
    win.set_default_size(360, 520)
    player_row = PlayerRow(0, devices)
    win.set_child(player_row)

    try:
        if settings is not None:
            settings.set_property("gtk-enable-animations", True)
        win.present()
        _pump_events(0.2)

        # The closed dropdown button stays a compact ellipsized label, not a marquee row.
        button = player_row.joystick_row.get_first_child()
        assert not _find_descendants(button, MarqueeLabel)

        # Prevent external window focus changes from auto-dismissing the popover mid-test.
        for popover in _find_descendants(player_row.joystick_row, Gtk.Popover):
            popover.set_autohide(False)

        # Select the long controller and open the dropdown list.
        player_row.joystick_row.set_selected(3)
        button.emit("clicked")
        _pump_events(0.2)

        option_rows = _find_descendants(player_row.joystick_row, _ControllerOptionRow)
        assert [opt.label.get_text() for opt in option_rows] == [
            "None",
            "Xbox Wireless Controller",
            "Xbox Wireless Controller",
            long_name,
        ]
        assert all(opt.dot.get_icon_name() == "twinverse-dot-symbolic" for opt in option_rows)
        assert [opt.is_selected_option() for opt in option_rows] == [False, False, False, True]
        assert [opt.dot.get_opacity() for opt in option_rows] == [0.0, 0.0, 0.0, 1.0]
        assert option_rows[3].has_css_class("is-selected")
        assert not option_rows[0].has_css_class("is-selected")

        # Long controller names scroll inside the open list; short names remain still.
        assert option_rows[0].label.get_overflow() == 0.0
        assert not option_rows[0].label.is_scrolling()
        assert option_rows[3].label.get_overflow() > 0.0
        assert option_rows[3].label.is_scrolling()

        # Selecting one of two identically named controllers marks only that exact entry.
        player_row.joystick_row.set_selected(2)
        _pump_events(0.05)
        assert [opt.is_selected_option() for opt in option_rows] == [False, False, True, False]
        assert [opt.dot.get_opacity() for opt in option_rows] == [0.0, 0.0, 1.0, 0.0]

        # Closing the popover stops marquee scrolling and resets offsets.
        button.emit("clicked")
        _pump_events(0.15)
        assert not option_rows[3].label.is_scrolling()
        assert option_rows[3].label.get_scroll_offset() == 0.0

        # Refreshing devices keeps the selected controller's dot synchronized on the rebuilt model.
        player_row.update_devices(devices)
        _pump_events(0.1)
        refreshed_rows = _find_descendants(player_row.joystick_row, _ControllerOptionRow)
        assert [opt.is_selected_option() for opt in refreshed_rows] == [False, False, True, False]
    finally:
        if settings is not None:
            settings.set_property("gtk-enable-animations", previous_animations)
        win.destroy()
        _pump_events(0.05)


def test_controller_dropdown_remembers_disconnected_option_and_retranslates():
    """Remembered disconnected controllers appear in the popover, retranslate live, and prune on clear."""
    _require_gtk_display()
    previous_lang = get_language_preference()
    devices = {
        "joystick": [
            {"id": "/dev/input/by-id/usb-xbox-event-joystick", "name": "Xbox Wireless Controller"},
        ],
        "audio": [],
    }
    remembered_id = "/dev/input/by-id/usb-dualsense-event-joystick"

    win = Gtk.Window()
    win.set_default_size(360, 520)
    player_row = PlayerRow(1, devices)
    win.set_child(player_row)

    try:
        set_language(LANGUAGE_EN)
        player_row.retranslate()
        player_row.load_config(
            PlayerInstanceConfig(
                PHYSICAL_DEVICE_ID=remembered_id,
                PHYSICAL_DEVICE_NAME="DualSense Controller",
            )
        )
        win.present()
        _pump_events(0.15)

        button = player_row.joystick_row.get_first_child()
        for popover in _find_descendants(player_row.joystick_row, Gtk.Popover):
            popover.set_autohide(False)

        button.emit("clicked")
        _pump_events(0.15)

        option_rows = _find_descendants(player_row.joystick_row, _ControllerOptionRow)
        assert [opt.label.get_text() for opt in option_rows] == [
            "None",
            "Xbox Wireless Controller",
            "DualSense Controller (Disconnected)",
        ]
        assert [opt.is_selected_option() for opt in option_rows] == [False, False, True]
        assert [opt.is_disconnected_option() for opt in option_rows] == [False, False, True]
        assert option_rows[2].has_css_class("is-disconnected")
        assert not option_rows[1].has_css_class("is-disconnected")
        assert player_row.joystick_row.has_css_class("controller-disconnected")

        # Switching language retranslates the disconnected label in place while preserving selection.
        set_language(LANGUAGE_PT_BR)
        player_row.retranslate()
        _pump_events(0.1)
        model = player_row.joystick_row.get_model()
        assert [model.get_string(i) for i in range(model.get_n_items())] == [
            "Nenhum",
            "Xbox Wireless Controller",
            "DualSense Controller (Desconectado)",
        ]
        assert player_row.joystick_row.get_selected() == 2
        assert player_row.get_config().physical_device_id == remembered_id
        assert player_row.get_config().physical_device_name == "DualSense Controller"

        set_language(LANGUAGE_EN)
        player_row.retranslate()
        _pump_events(0.1)
        assert [model.get_string(i) for i in range(model.get_n_items())] == [
            "None",
            "Xbox Wireless Controller",
            "DualSense Controller (Disconnected)",
        ]

        # Selecting None prunes the stale disconnected entry cleanly even while the popover is open.
        player_row.joystick_row.set_selected(0)
        _pump_events(0.1)
        assert [model.get_string(i) for i in range(model.get_n_items())] == [
            "None",
            "Xbox Wireless Controller",
        ]
        assert not player_row.joystick_row.has_css_class("controller-disconnected")
        assert player_row.get_config().physical_device_id is None
        assert player_row.get_config().physical_device_name is None
    finally:
        set_language(previous_lang)
        win.destroy()
        _pump_events(0.05)


def test_controller_dropdown_blocks_duplicate_selection_and_shows_owner_player_badge():
    """Controllers assigned to one player become non-activatable with the owning player's number for other players."""
    _require_gtk_display()
    devices = {
        "displays": [{"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080}],
        "joystick": [
            {"id": "/dev/input/by-id/pad-a", "name": "Xbox Wireless Controller"},
            {"id": "/dev/input/by-id/pad-b", "name": "DualSense Wireless Controller"},
        ],
        "audio": [],
    }
    profile = Profile(NUM_PLAYERS=2, PLAYERS=[PlayerInstanceConfig(), PlayerInstanceConfig()])

    win = Gtk.Window()
    win.set_default_size(960, 620)
    page = LayoutSettingsPage()
    page.load_data(profile, devices, {0: True, 1: True})
    win.set_child(page)

    try:
        win.present()
        _pump_events(0.15)

        p1, p2 = page.player_rows[0], page.player_rows[1]
        p2_changes = []
        p2.connect("settings-changed", lambda *_: p2_changes.append(True))

        # Player 1 selects pad-a.
        p1.joystick_row.set_selected(1)
        _pump_events(0.1)
        assert p1.get_selected_controller_id() == "/dev/input/by-id/pad-a"

        # Open Player 2's dropdown popover and inspect option rows & GtkListItem flags.
        page.select_player(1)
        _pump_events(0.1)
        button = p2.joystick_row.get_first_child()
        for popover in _find_descendants(p2.joystick_row, Gtk.Popover):
            popover.set_autohide(False)
        button.emit("clicked")
        _pump_events(0.15)

        option_rows = _find_descendants(p2.joystick_row, _ControllerOptionRow)
        assert len(option_rows) == 3
        # Option 0 ("None") and Option 2 ("pad-b") are free; Option 1 ("pad-a") belongs to Player 01.
        assert option_rows[0].owner_player() is None
        assert option_rows[1].owner_player() == 0
        assert option_rows[1].owner_badge.get_label() == "01"
        assert option_rows[1].owner_badge.get_visible()
        assert option_rows[1].has_css_class("is-taken")
        assert not any(c.startswith("player-color-") for c in option_rows[1].owner_badge.get_css_classes())
        assert not option_rows[1].dot.get_visible()
        assert option_rows[1].dot.get_opacity() == 0.0
        assert option_rows[2].owner_player() is None
        assert not option_rows[2].owner_badge.get_visible()
        assert option_rows[2].dot.get_visible()

        # Verify the underlying Gtk.ListItem for the taken controller is non-activatable and non-selectable.
        taken_item = p2._bound_controller_items[option_rows[1]]
        free_item = p2._bound_controller_items[option_rows[2]]
        assert not taken_item.get_activatable()
        assert not taken_item.get_selectable()
        assert free_item.get_activatable()
        assert free_item.get_selectable()

        # Programmatic/keyboard attempt on Player 2 to select pad-a is rejected without emitting settings-changed.
        p2.joystick_row.set_selected(1)
        _pump_events(0.05)
        assert p2.joystick_row.get_selected() == 0
        assert p2.get_selected_controller_id() is None
        assert p2_changes == []

        # Player 2 can still select the free controller (pad-b).
        p2.joystick_row.set_selected(2)
        _pump_events(0.05)
        assert p2.get_selected_controller_id() == "/dev/input/by-id/pad-b"
        assert len(p2_changes) == 1

        # Releasing pad-a from Player 1 immediately unlocks it in Player 2's live popover.
        p1.joystick_row.set_selected(0)
        _pump_events(0.1)
        assert option_rows[1].owner_player() is None
        assert not option_rows[1].has_css_class("is-taken")
        assert not option_rows[1].owner_badge.get_visible()
        assert option_rows[1].dot.get_visible()
        assert taken_item.get_activatable()
        assert taken_item.get_selectable()

        # Player 2 can now take pad-a cleanly.
        p2.joystick_row.set_selected(1)
        _pump_events(0.05)
        assert p2.get_selected_controller_id() == "/dev/input/by-id/pad-a"
    finally:
        win.destroy()
        _pump_events(0.05)


def test_layout_page_deduplicates_legacy_duplicate_controllers_and_frees_on_player_remove():
    """Legacy duplicate assignments are resolved on load, and removing a player frees their controller."""
    _require_gtk_display()
    devices = {
        "displays": [{"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080}],
        "joystick": [
            {"id": "/dev/input/by-id/pad-a", "name": "Xbox Wireless Controller"},
        ],
        "audio": [],
    }
    duplicate_profile = Profile(
        NUM_PLAYERS=2,
        PLAYERS=[
            PlayerInstanceConfig(PHYSICAL_DEVICE_ID="/dev/input/by-id/pad-a", PHYSICAL_DEVICE_NAME="Xbox"),
            PlayerInstanceConfig(PHYSICAL_DEVICE_ID="/dev/input/by-id/pad-a", PHYSICAL_DEVICE_NAME="Xbox"),
        ],
    )

    page = LayoutSettingsPage()
    page.load_data(duplicate_profile, devices, {0: True, 1: True})
    p1, p2 = page.player_rows[0], page.player_rows[1]
    assert p1.get_selected_controller_id() == "/dev/input/by-id/pad-a"
    assert p2.get_selected_controller_id() is None

    # Removing Player 1 frees pad-a so Player 2 can immediately claim it.
    assert page.remove_player(0)
    assert len(page.player_rows) == 1
    remaining_p2 = page.player_rows[0]
    remaining_p2.joystick_row.set_selected(1)
    assert remaining_p2.get_selected_controller_id() == "/dev/input/by-id/pad-a"


def test_audio_dropdown_supports_dots_disconnected_yellow_and_non_blocking_shared_player_numbers():
    """Audio dropdown shows blue/yellow dots and shared player numbers without blocking reuse."""
    _require_gtk_display()
    previous_lang = get_language_preference()
    devices = {
        "displays": [{"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080}],
        "joystick": [],
        "audio": [
            {"id": "sink-hdmi", "name": "HDMI Stereo Output"},
            {"id": "sink-headset", "name": "USB Headset"},
        ],
    }
    profile = Profile(
        NUM_PLAYERS=3,
        PLAYERS=[
            PlayerInstanceConfig(AUDIO_DEVICE_ID="sink-hdmi", AUDIO_DEVICE_NAME="HDMI Stereo Output"),
            PlayerInstanceConfig(),
            PlayerInstanceConfig(AUDIO_DEVICE_ID="sink-bt-missing", AUDIO_DEVICE_NAME="Bluetooth Speaker"),
        ],
    )

    win = Gtk.Window()
    win.set_default_size(960, 620)
    page = LayoutSettingsPage()

    try:
        set_language(LANGUAGE_EN)
        page.load_data(profile, devices, {0: True, 1: True, 2: True})
        win.set_child(page)
        win.present()
        _pump_events(0.15)

        p1, p2, p3 = page.player_rows[0], page.player_rows[1], page.player_rows[2]

        # Player 2 opens Audio dropdown: Default has blue dot; HDMI shows "01" and stays selectable.
        page.select_player(1)
        _pump_events(0.1)
        p2_btn = p2.audio_row.get_first_child()
        for popover in _find_descendants(p2.audio_row, Gtk.Popover):
            popover.set_autohide(False)
        p2_btn.emit("clicked")
        _pump_events(0.15)

        p2_opts = _find_descendants(p2.audio_row, _ControllerOptionRow)
        assert [opt.label.get_text() for opt in p2_opts] == ["Default", "HDMI Stereo Output", "USB Headset"]
        assert [opt.is_selected_option() for opt in p2_opts] == [True, False, False]
        assert p2_opts[0].dot.get_opacity() == 1.0
        assert not p2_opts[0].has_css_class("is-disconnected")
        assert p2_opts[1].other_players() == (0,)
        assert p2_opts[1].owner_badge.get_label() == "01"
        assert p2_opts[1].owner_badge.get_visible()
        assert not p2_opts[1].dot.get_visible()
        assert not p2_opts[1].has_css_class("is-taken")
        hdmi_item = p2._bound_audio_items[p2_opts[1]]
        assert hdmi_item.get_activatable()
        assert hdmi_item.get_selectable()

        # Player 2 can share the exact same HDMI audio output with Player 1; both "01" and its own dot show.
        p2.audio_row.set_selected(1)
        _pump_events(0.1)
        assert p2.get_selected_audio_id() == "sink-hdmi"
        assert p2_opts[1].is_selected_option()
        assert p2_opts[1].owner_badge.get_visible()
        assert p2_opts[1].owner_badge.get_label() == "01"
        assert p2_opts[1].dot.get_visible()
        assert p2_opts[1].dot.get_opacity() == 1.0

        # Player 3 has a remembered disconnected audio device (yellow dot) and sees "01, 02" on HDMI.
        p2_btn.emit("clicked")
        page.select_player(2)
        _pump_events(0.1)
        p3_btn = p3.audio_row.get_first_child()
        for popover in _find_descendants(p3.audio_row, Gtk.Popover):
            popover.set_autohide(False)
        p3_btn.emit("clicked")
        _pump_events(0.15)

        p3_opts = _find_descendants(p3.audio_row, _ControllerOptionRow)
        assert [opt.label.get_text() for opt in p3_opts] == [
            "Default",
            "HDMI Stereo Output",
            "USB Headset",
            "Bluetooth Speaker (Disconnected)",
        ]
        assert p3_opts[1].other_players() == (0, 1)
        assert p3_opts[1].owner_badge.get_label() == "01, 02"
        assert p3_opts[3].is_selected_option()
        assert p3_opts[3].is_disconnected_option()
        assert p3_opts[3].has_css_class("is-disconnected")
        assert p3_opts[3].dot.get_opacity() == 1.0
        assert p3.audio_row.has_css_class("controller-disconnected")
        assert p3.get_config().audio_device_id == "sink-bt-missing"
        assert p3.get_config().audio_device_name == "Bluetooth Speaker"

        # Switching Player 3 to USB Headset prunes the stale disconnected audio entry.
        p3.audio_row.set_selected(2)
        _pump_events(0.1)
        assert not p3.audio_row.has_css_class("controller-disconnected")
        assert p3.audio_row.get_model().get_n_items() == 3
        assert p1.get_selected_audio_id() == "sink-hdmi"
    finally:
        set_language(previous_lang)
        win.destroy()
        _pump_events(0.05)
