"""Studio-styled floating toast overlay for non-blocking session feedback."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from src.gui.notifications import BUSY, ERROR, INFO

# The CSS class that gives the toast card its semantic styling per level.
LEVEL_CLASSES = {
    INFO: "toast-info",
    ERROR: "toast-error",
    BUSY: "toast-busy",
}

# Custom in-app symbolic icons matching the Twinverse studio icon set.
TOAST_ICONS = {
    INFO: "twinverse-info-symbolic",
    ERROR: "twinverse-error-symbolic",
    BUSY: "twinverse-refresh-symbolic",
}

LEVEL_TITLES = {
    INFO: "NOTICE",
    ERROR: "ERROR",
    BUSY: "WORKING",
}


class ToastOverlay(Gtk.Overlay):
    """A floating studio notification pill with semantic badge and quick dismiss."""

    def __init__(self, **kwargs):
        """Initialize the overlay and the studio-styled toast card."""
        super().__init__(**kwargs)
        self._timeout_id = 0

        self._icon = Gtk.Image(
            pixel_size=16,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            hexpand=True,
            vexpand=True,
        )
        self._icon.add_css_class("toast-icon")

        self._badge = Gtk.Box(
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            hexpand=False,
            vexpand=False,
        )
        self._badge.set_size_request(32, 32)
        self._badge.add_css_class("toast-badge")
        self._badge.append(self._icon)

        self._title = Gtk.Label(xalign=0)
        self._title.add_css_class("toast-title")

        self._label = Gtk.Label(wrap=True, justify=Gtk.Justification.LEFT, xalign=0)
        self._label.set_max_width_chars(48)
        self._label.add_css_class("toast-message")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER, hexpand=True)
        body.add_css_class("toast-body")
        body.append(self._title)
        body.append(self._label)

        self._dismiss_button = Gtk.Button(icon_name="twinverse-close-symbolic", valign=Gtk.Align.CENTER)
        self._dismiss_button.add_css_class("flat")
        self._dismiss_button.add_css_class("toast-dismiss")
        self._dismiss_button.set_tooltip_text("Dismiss")
        self._dismiss_button.update_property([Gtk.AccessibleProperty.LABEL], ["Dismiss notification"])
        self._dismiss_button.connect("clicked", lambda *_: self.dismiss())

        self._card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._card.append(self._badge)
        self._card.append(body)
        self._card.append(self._dismiss_button)
        self._card.add_css_class("toast-card")

        self._revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=220,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.END,
            margin_start=16,
            margin_end=16,
            margin_bottom=18,
        )
        self._revealer.set_child(self._card)
        self.add_overlay(self._revealer)

    def show_toast(self, message: str, level: str = INFO, timeout: int = 3):
        """Show a non-blocking studio toast over the window, replacing any previous one."""
        self._icon.set_from_icon_name(TOAST_ICONS.get(level, TOAST_ICONS[INFO]))
        if hasattr(self, "_title"):
            self._title.set_text(LEVEL_TITLES.get(level, LEVEL_TITLES[INFO]))
        self._label.set_text(message)

        for name in LEVEL_CLASSES.values():
            self._card.remove_css_class(name)
        self._card.add_css_class(LEVEL_CLASSES.get(level, LEVEL_CLASSES[INFO]))

        self._revealer.set_reveal_child(True)
        self._schedule_hide(timeout)

    def dismiss(self):
        """Hide the active toast immediately and cancel any pending auto-hide timer."""
        if self._timeout_id:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = 0
        self._revealer.set_reveal_child(False)

    def _schedule_hide(self, timeout: int):
        """Hide the card after the time it was given."""
        if self._timeout_id:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = 0
        if timeout <= 0:
            return
        self._timeout_id = GLib.timeout_add_seconds(timeout, self._on_timeout)

    def _on_timeout(self) -> bool:
        """Take the card away when the time is over."""
        self._timeout_id = 0
        self._revealer.set_reveal_child(False)
        return False
