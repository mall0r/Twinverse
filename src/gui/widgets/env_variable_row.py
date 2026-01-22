"""
Environment variable row widget module.

This module provides a custom widget for environment variable input.
"""

import gi
from gi.repository import Adw, GObject, Gtk

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class EnvVariableRow(Adw.ActionRow):
    """Widget for editing a single environment variable."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "remove-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, key: str = "", value: str = "", **kwargs):
        """Initialize the environment variable row."""
        super().__init__(**kwargs)
        self.get_style_context().add_class("env-var-row")
        self._build_ui(key, value)

    def _build_ui(self, key: str, value: str):
        """Build the UI."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.get_style_context().add_class("env-var-box")

        # Key entry
        self.key_entry = Gtk.Entry(placeholder_text="KEY")
        self.key_entry.get_style_context().add_class("env-key-entry")
        self.key_entry.set_text(key)
        self.key_entry.connect("changed", lambda *args: self.emit("changed"))

        # Equals label
        equals_label = Gtk.Label(label="=")

        # Value entry
        self.value_entry = Gtk.Entry(placeholder_text="VALUE")
        self.value_entry.get_style_context().add_class("env-value-entry")
        self.value_entry.set_text(value)
        self.value_entry.connect("changed", lambda *args: self.emit("changed"))

        # Remove button
        remove_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        remove_btn.get_style_context().add_class("remove-button")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", lambda *args: self.emit("remove-requested"))

        # Pack widgets
        box.append(self.key_entry)
        box.append(equals_label)
        box.append(self.value_entry)
        box.append(remove_btn)

        self.set_child(box)

    def get_values(self) -> tuple[str, str]:
        """Get the key and value."""
        key = (self.key_entry.get_text() or "").strip()
        value = self.value_entry.get_text() if self.value_entry else ""
        return key, value
