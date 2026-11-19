"""Main application class."""

# flake8: noqa: E402

import logging
import os
import sys
from typing import Optional, Sequence

import gi

gi.require_version("Gtk", "4.0")  # noqa: E402
gi.require_version("Adw", "1")  # noqa: E402

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from src.core.config import Config
from src.core.utils import Utils
from src.gui.presenters import MainPresenter

logger = logging.getLogger(__name__)


class TwinverseApplication(Adw.Application):
    """Main application class for the Twinverse GUI application."""

    def __init__(self, **kwargs):
        """Initialize the application and set up resources."""
        super().__init__(application_id=Config.APP_ID, **kwargs)
        self.base_path = Utils.get_base_path()
        self.win = None
        self._applying_cursor_theme = False

        logger.debug("Loading application resources from %s", self.base_path)
        self._load_resources()
        self.connect("activate", self.on_activate)
        self.connect("startup", self.on_startup)
        self._initialize_theme()

    def _initialize_theme(self):
        """Initialize the theme to system default."""
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _watch_cursor_theme(self) -> None:
        """Follow the cursor theme setting for as long as the application runs.

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
        """Apply the cursor theme configured by the user.

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
            logger.debug("Applied cursor theme %s (size %d)", theme_name, cursor_size)
        except Exception:  # noqa: BLE001 - a missing display must not block startup
            logger.warning("Could not apply the cursor theme", exc_info=True)
        finally:
            self._applying_cursor_theme = False

    def on_startup(self, app):
        """Handle the application startup event."""
        # The display only exists once the application starts, so the cursor
        # theme is applied here and not while the object is built.
        self._watch_cursor_theme()
        self._apply_cursor_theme()
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_resource_path("/io/github/mall0r/Twinverse/icons")
        logger.info("Application startup completed (pid=%d)", os.getpid())

    def _load_resources(self):
        """Load application resources."""
        resource_path = self.base_path / "res" / "twinverse.gresource"
        if resource_path.exists():
            resources = Gio.Resource.load(str(resource_path))
            Gio.resources_register(resources)
            logger.debug("Application resources registered")
        else:
            logger.warning("Resource file not found: %s", resource_path)

    def on_activate(self, app):
        """Handle the application activation event."""
        logger.debug("Application activation requested")
        try:
            if self.win is not None:
                # A second activation would build a second window and a second
                # set of instances, and the first one would be lost.
                logger.debug("Presenting the existing window")
                self.win.present()
                return

            self._load_css()
            presenter = MainPresenter(app)
            self.win = presenter.window
            self.win.present()
            logger.info("Main window presented")
        except Exception:
            logger.exception("Could not create the main window")
            raise

    def _load_css(self):
        """Load application CSS."""
        css_provider = Gtk.CssProvider()
        stylesheet = self.base_path / "res" / "styles" / "style.css"
        if stylesheet.exists():
            css_provider.load_from_path(str(stylesheet))
        else:
            css_provider.load_from_resource("/io/github/mall0r/Twinverse/styles/style.css")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    @staticmethod
    def run_gui(argv: Optional[Sequence[str]] = None) -> int:
        """Launch the GUI application and return its exit status."""
        os.environ.setdefault("GSK_RENDERER", "gl")
        arguments = list(sys.argv if argv is None else [sys.argv[0], *argv])
        logger.info("Starting the GUI")
        app = TwinverseApplication()
        try:
            result = app.run(arguments)
            logger.info("GUI stopped with status %s", result)
            return int(result)
        except Exception:
            logger.exception("The GUI terminated unexpectedly")
            raise
