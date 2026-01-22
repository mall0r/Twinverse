"""
Text input dialog module.

This module provides a text input dialog.
"""

import gi
from gi.repository import Gtk

from .base_dialog import BaseDialog

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class TextInputDialog(BaseDialog):
    """Dialog for getting text input from the user."""

    def __init__(self, parent, title: str, message: str):
        """Initialize the text input dialog."""
        super().__init__(parent, title, message)
        self.entry = Gtk.Entry()
        self.set_extra_child(self.entry)
        self.add_response("ok", "OK")
        self.add_response("cancel", "Cancel")
        self.set_default_response("ok")

    def get_input(self) -> str:
        """Get the text input from the dialog."""
        return self.entry.get_text()
