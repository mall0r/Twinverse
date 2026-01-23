"""
Error dialog module.

This module provides an error dialog.
"""

import gi

from .base_dialog import BaseDialog

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class ErrorDialog(BaseDialog):
    """Dialog for displaying error messages."""

    def __init__(self, parent, title: str, message: str):
        """Initialize the error dialog."""
        super().__init__(parent, title, message)
        self.add_response("ok", "OK")
        self.set_default_response("ok")
