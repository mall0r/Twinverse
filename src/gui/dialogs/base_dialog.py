"""Base class for dialogs."""

import gi
from gi.repository import Adw

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class BaseDialog(Adw.AlertDialog):
    """Base dialog class."""

    def __init__(self, parent, title: str, message: str, **kwargs):
        """Initialize the base dialog."""
        super().__init__(heading=title, body=message, **kwargs)
        self._parent = parent

    def present(self, parent=None):
        """Present the dialog attached to its configured parent widget."""
        super().present(self._parent if parent is None else parent)
