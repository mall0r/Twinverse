"""Compact environment variable editor for the player inspector."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GObject, Gtk

from src.core.i18n import t


class EnvVariableRow(Gtk.Box):
    """Edit one key/value pair without imposing a preferences-row width."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "remove-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, key: str = "", value: str = "", **kwargs):
        """Build labelled, vertically stacked fields for a narrow inspector."""
        super().__init__(**kwargs)
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(8)
        self.add_css_class("inspector-env-row")

        key_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        key_field, self.key_label, self.key_entry = self._create_field(
            t("env.key_label"), t("env.key_placeholder"), key
        )
        self.key_entry.add_css_class("inspector-env-key")
        key_line.append(key_field)

        self.remove_button = Gtk.Button.new_from_icon_name("twinverse-trash-symbolic")
        self.remove_button.add_css_class("flat")
        self.remove_button.add_css_class("inspector-env-remove")
        self.remove_button.set_valign(Gtk.Align.END)
        self.remove_button.set_tooltip_text(t("env.remove_tooltip"))
        self.remove_button.connect("clicked", lambda *_args: self.emit("remove-requested"))
        key_line.append(self.remove_button)
        self.append(key_line)

        value_field, self.value_label, self.value_entry = self._create_field(
            t("env.value_label"), t("env.value_placeholder"), value
        )
        self.value_entry.add_css_class("inspector-env-value")
        self.append(value_field)

    def _create_field(self, title: str, placeholder: str, text: str):
        field = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        label = Gtk.Label(label=title, use_underline=True, xalign=0)
        label.add_css_class("inspector-field-label")
        field.append(label)

        entry = Gtk.Entry(placeholder_text=placeholder, hexpand=True)
        entry.set_width_chars(1)
        entry.set_max_width_chars(24)
        entry.add_css_class("inspector-entry")
        entry.set_text(text)
        entry.connect("changed", lambda *_args: self.emit("changed"))
        label.set_mnemonic_widget(entry)
        field.append(entry)
        return field, label, entry

    def retranslate(self):
        """Update labels, placeholders, and tooltips for the active language."""
        self.key_label.set_label(t("env.key_label"))
        self.key_entry.set_placeholder_text(t("env.key_placeholder"))
        self.value_label.set_label(t("env.value_label"))
        self.value_entry.set_placeholder_text(t("env.value_placeholder"))
        self.remove_button.set_tooltip_text(t("env.remove_tooltip"))

    def get_values(self) -> tuple[str, str]:
        """Normalize the key, but preserve every character of the value."""
        return self.key_entry.get_text().strip(), self.value_entry.get_text()
