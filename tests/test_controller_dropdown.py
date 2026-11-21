"""Behavioral coverage for the Player Setup controller dropdown list and marquee labels."""

import time

import gi
import pytest

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from src.gui.widgets.marquee_label import (  # noqa: E402
    MarqueeLabel,
    compute_marquee_offset,
)
from src.gui.widgets.player_row import PlayerRow, _ControllerOptionRow  # noqa: E402


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
