"""Check the message that appears over the window."""

from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from src.gui.notifications import BUSY, ERROR, INFO  # noqa: E402
from src.gui.widgets.toast import LEVEL_CLASSES, TOAST_ICONS, ToastOverlay  # noqa: E402


def _overlay():
    """Build the parts of the overlay that the toast uses."""
    overlay = Mock()
    overlay._timeout_id = 0
    return overlay


def test_a_failure_is_outlined_in_red():
    """A failure is not read as a notice."""
    overlay = _overlay()

    ToastOverlay.show_toast(overlay, "a Steam nao abriu", ERROR)

    overlay._card.add_css_class.assert_called_once_with("toast-error")


def test_a_message_of_a_work_in_progress_is_not_an_error():
    """A client that is starting, or updating, is only busy."""
    overlay = _overlay()

    ToastOverlay.show_toast(overlay, "Starting the Steam client…", BUSY)

    overlay._card.add_css_class.assert_called_once_with("toast-busy")


def test_the_card_takes_the_icon_of_the_message():
    """The card shows the custom symbolic icon that represents what happened."""
    overlay = _overlay()

    ToastOverlay.show_toast(overlay, "a Steam nao abriu", ERROR)

    assert overlay._icon.set_from_icon_name.call_args[0][0] == TOAST_ICONS[ERROR]


def test_the_look_of_the_previous_message_is_taken_away():
    """A message that comes after a failure is not red anymore."""
    overlay = _overlay()

    ToastOverlay.show_toast(overlay, "a Steam nao abriu", ERROR)
    ToastOverlay.show_toast(overlay, "Steam started", INFO)

    removed = [call[0][0] for call in overlay._card.remove_css_class.call_args_list]
    assert "toast-error" in removed
    overlay._card.add_css_class.assert_called_with(LEVEL_CLASSES[INFO])


def test_dismiss_hides_the_toast_immediately():
    """Dismissing cancels any active toast and collapses the revealer."""
    overlay = _overlay()

    ToastOverlay.dismiss(overlay)

    overlay._revealer.set_reveal_child.assert_called_once_with(False)


def test_toast_icon_is_centered_inside_badge():
    """The toast icon sits centered inside its 32x32 badge without shifting the badge."""
    if not Gtk.init_check():
        pytest.skip("A GTK display is required")

    win = Gtk.Window()
    win.set_default_size(600, 400)
    overlay = ToastOverlay()
    win.set_child(overlay)
    try:
        assert overlay._icon.get_halign() == Gtk.Align.CENTER
        assert overlay._icon.get_valign() == Gtk.Align.CENTER
        assert overlay._icon.get_hexpand() is True
        assert overlay._icon.get_vexpand() is True
        assert overlay._icon.get_pixel_size() == 16
        assert overlay._badge.get_hexpand() is False
        assert overlay._badge.get_vexpand() is False

        overlay.show_toast("Instance 1 started", INFO, timeout=0)
        win.present()
        context = GLib.MainContext.default()
        for _ in range(30):
            while context.pending():
                context.iteration(False)

        ok_badge, badge_rect = overlay._badge.compute_bounds(overlay._card)
        ok_icon, icon_rect = overlay._icon.compute_bounds(overlay._badge)
        assert ok_badge and ok_icon
        assert badge_rect.size.width == pytest.approx(32.0, abs=1.0)
        assert badge_rect.size.height == pytest.approx(32.0, abs=1.0)
        assert icon_rect.origin.x == pytest.approx((badge_rect.size.width - icon_rect.size.width) / 2, abs=1.0)
        assert icon_rect.origin.y == pytest.approx((badge_rect.size.height - icon_rect.size.height) / 2, abs=1.0)
    finally:
        win.close()
