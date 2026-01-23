"""
Confirmation dialog module.

This module provides a confirmation dialog.
"""

import gi

from .base_dialog import BaseDialog

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class ConfirmationDialog(BaseDialog):
    """Dialog for confirming user actions."""

    def __init__(self, parent, title: str, message: str):
        """Initialize the confirmation dialog."""
        super().__init__(parent, title, message)
        self.add_response("ok", "OK")
        self.add_response("cancel", "Cancel")
        self.set_default_response("cancel")
