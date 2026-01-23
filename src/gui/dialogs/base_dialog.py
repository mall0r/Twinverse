"""
Base dialog module.

This module provides a base class for dialogs.
"""

import gi
from gi.repository import Adw

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class BaseDialog(Adw.MessageDialog):
    """Base dialog class."""

    def __init__(self, parent, title: str, message: str, **kwargs):
        """Initialize the base dialog."""
        super().__init__(transient_for=parent, modal=True, title=title, body=message, **kwargs)
