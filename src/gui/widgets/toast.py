"""The message that appears over the window.

The toast tells the user what the application is doing, and how important
that is. A failure is shown as an error, with the icon of an error and a red
border, and the other messages are only information.
"""

import gi
from gi.repository import GLib, Gtk

from src.gui.notifications import BUSY, ERROR, ICONS, INFO

gi.require_version("Gtk", "4.0")

# The class that gives the card the look of each level.
LEVEL_CLASSES = {
    INFO: "toast-info",
    ERROR: "toast-error",
    BUSY: "toast-busy",
}


class ToastOverlay(Gtk.Overlay):
    """A card over the window, that tells the user something."""

    def __init__(self, **kwargs):
        """Initialize the overlay and the card that it holds."""
        super().__init__(**kwargs)
        self._timeout_id = 0

        self._icon = Gtk.Image()
        self._icon.add_css_class("toast-icon")

        self._label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, xalign=0.5)
        self._label.set_max_width_chars(60)

        self._card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._card.append(self._icon)
        self._card.append(self._label)
        self._card.add_css_class("toast-card")

        self._revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.END,
            margin_start=12,
            margin_end=12,
            margin_bottom=12,
        )
        self._revealer.set_child(self._card)
        self.add_overlay(self._revealer)

    def show_toast(self, message: str, level: str = INFO, timeout: int = 3):
        """
        Show a message over the window, without blocking it.

        The message goes away on its own, and the next one replaces it
        instead of waiting in a queue. The level of the message decides the
        icon and the look of the card.
        """
        self._icon.set_from_icon_name(ICONS.get(level, ICONS[INFO]))
        self._label.set_text(message)

        for name in LEVEL_CLASSES.values():
            self._card.remove_css_class(name)
        self._card.add_css_class(LEVEL_CLASSES.get(level, LEVEL_CLASSES[INFO]))

        self._revealer.set_reveal_child(True)
        self._schedule_hide(timeout)

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
