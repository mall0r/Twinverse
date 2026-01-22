"""
Application module for the Twinverse application.

This module provides the main application class.
"""

# flake8: noqa: E402

import os
import sys

import gi

gi.require_version("Gtk", "4.0")  # noqa: E402
gi.require_version("Adw", "1")  # noqa: E402

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from src.core import Logger, Utils
from src.core.config import Config
from src.gui.presenters import MainPresenter


class TwinverseApplication(Adw.Application):
    """Main application class for the Twinverse GUI application."""

    def __init__(self, **kwargs):
        """Initialize the application and set up resources."""
        super().__init__(application_id="io.github.mall0r.Twinverse", **kwargs)
        self.base_path = Utils.get_base_path()
        import logging

        self.logger = Logger("Twinverse-App", Config.LOG_DIR, reset=True, level=logging.DEBUG)

        print("Loading resources...")
        self._load_resources()
        print("Connecting activate signal...")
        self.connect("activate", self.on_activate)
        print("Activate signal connected")

        # Connect to startup signal as well to see what's happening
        self.connect("startup", self.on_startup)
        print("Startup signal connected")

        # Initialize theme to system default
        self._initialize_theme()

    def _initialize_theme(self):
        """Initialize the theme to system default."""
        # Set the theme to follow system preferences initially
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def on_startup(self, app):
        """Handle the application startup event."""
        print("Application startup called")

    def _load_resources(self):
        """Load application resources."""
        resource_path = self.base_path / "res" / "compiled.gresource"
        print(f"Looking for resource file at: {resource_path}")
        print(f"Resource file exists: {resource_path.exists()}")
        if resource_path.exists():
            resources = Gio.Resource.load(str(resource_path))
            Gio.Resource._register(resources)
            print("Resources registered")
        else:
            print("Resource file not found!")

    def on_activate(self, app):
        """Handle the application activation event."""
        print("Application activation started...")
        try:
            # Create presenter which will create the window
            print("Creating MainPresenter...")
            presenter = MainPresenter(app, self.logger)
            print("MainPresenter created successfully")

            self.win = presenter.window
            print(f"Window created: {self.win}")

            self._load_css()
            print("CSS loaded")

            print("About to present window...")
            self.win.present()
            print("Window presented")
        except Exception as e:
            print(f"Error in on_activate: {e}")
            import traceback

            traceback.print_exc()
            raise

    def _load_css(self):
        """Load application CSS."""
        css_provider = Gtk.CssProvider()
        css_path = self.base_path / "res" / "styles" / "style.css"
        if css_path.exists():
            css_provider.load_from_path(str(css_path))
            Gtk.StyleContext.add_provider_for_display(
                self.win.get_display(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )


def run_gui():
    """Launch the GUI application."""
    os.environ["GSK_RENDERER"] = "gl"

    print("Creating TwinverseApplication instance...")
    app = TwinverseApplication()
    print("TwinverseApplication instance created")

    # Print debug info
    print("Starting Twinverse Application...")

    # Check if we're running from command line or IDE
    print(f"sys.argv: {sys.argv}")

    try:
        print("About to call app.run()")
        result = app.run(sys.argv)
        print(f"app.run() returned with result: {result}")
        return result
    except Exception as e:
        print(f"Error running application: {e}")
        import traceback

        traceback.print_exc()
        raise
