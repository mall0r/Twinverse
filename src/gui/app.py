"""Main application class."""

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
        self._applying_cursor_theme = False
        import logging

        self.logger = Logger("Twinverse-App", Config.LOG_DIR, reset=True, level=logging.DEBUG)

        print("Loading resources...")
        self._load_resources()
        print("Connecting activate signal...")
        self.connect("activate", self.on_activate)
        print("Activate signal connected")

        self.connect("startup", self.on_startup)
        print("Startup signal connected")

        self._initialize_theme()

    def _initialize_theme(self):
        """Initialize the theme to system default."""
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _watch_cursor_theme(self) -> None:
        """
        Follow the cursor theme setting for as long as the application runs.

        The setting can change while the application is open, for example when
        the user picks another theme in the desktop settings. Re-applying the
        value keeps the cursor the user picked, both on the host and inside the
        sandbox of an AppImage or Flatpak.
        """
        settings = Gtk.Settings.get_default()
        if settings is None:
            return
        settings.connect("notify::gtk-cursor-theme-name", self._on_cursor_theme_changed)
        settings.connect("notify::gtk-cursor-theme-size", self._on_cursor_theme_changed)

    def _on_cursor_theme_changed(self, settings, _pspec) -> None:
        """Re-apply the cursor theme when the user changes the setting."""
        self._apply_cursor_theme()

    def _apply_cursor_theme(self) -> None:
        """
        Apply the cursor theme configured by the user.

        GTK resolves the cursor theme from the settings when they change, but
        the resolution can miss the theme on startup and leave the built-in
        default cursor in place instead of the configured one. Re-applying the
        configured value keeps the cursor the user picked, both on the host and
        inside the sandbox of an AppImage or Flatpak.
        """
        if self._applying_cursor_theme:
            return
        self._applying_cursor_theme = True
        try:
            settings = Gtk.Settings.get_default()
            if settings is None:
                return
            theme_name = str(settings.get_property("gtk-cursor-theme-name") or "default")
            cursor_size = int(settings.get_property("gtk-cursor-theme-size") or 24)
            settings.set_property("gtk-cursor-theme-name", theme_name)
            settings.set_property("gtk-cursor-theme-size", cursor_size)
            self.logger.debug(f"Applied cursor theme {theme_name} (size {cursor_size})")
        except Exception as e:
            self.logger.warning(f"Could not apply the cursor theme: {e}")
        finally:
            self._applying_cursor_theme = False

    def on_startup(self, app):
        """Handle the application startup event."""
        # The display only exists once the application starts, so the cursor
        # theme is applied here and not while the object is built.
        self._watch_cursor_theme()
        self._apply_cursor_theme()
        print("Application startup called")

    def _load_resources(self):
        """Load application resources."""
        resource_path = self.base_path / "res" / "twinverse.gresource"
        print(f"Looking for resource file at: {resource_path}")
        print(f"Resource file exists: {resource_path.exists()}")
        if resource_path.exists():
            resources = Gio.Resource.load(str(resource_path))
            Gio.resources_register(resources)
            print("Resources registered")
        else:
            print("Resource file not found!")

    def on_activate(self, app):
        """Handle the application activation event."""
        print("Application activation started...")
        try:
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
        css_provider.load_from_resource("/io/github/mall0r/Twinverse/styles/style.css")
        Gtk.StyleContext.add_provider_for_display(
            self.win.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    @staticmethod
    def run_gui() -> None:
        """Launch the GUI application."""
        os.environ["GSK_RENDERER"] = "gl"

        print("Creating TwinverseApplication instance...")
        app = TwinverseApplication()
        print("TwinverseApplication instance created")

        print("Starting Twinverse Application...")

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
