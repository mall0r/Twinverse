"""
Main window module for the Twinverse application.

This module provides the main window UI - presentation only.
"""

import gi
from gi.repository import Adw, Gio, Gtk

from src.gui.dialogs import ErrorDialog
from src.gui.pages import LayoutSettingsPage

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class MainWindow(Adw.ApplicationWindow):
    """Main window class - handles UI presentation only."""

    def __init__(self, application, presenter, *args, **kwargs):
        """Initialize the main window."""
        super().__init__(*args, application=application, **kwargs)
        self._presenter = presenter
        self.set_title("Twinverse")
        self.set_default_size(820, 750)
        self.theme_toggle_button = None  # Store reference to theme toggle button
        self._build_ui()
        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        """Build the user interface."""
        self.toolbar_view = Adw.ToolbarView()
        self.toolbar_view.get_style_context().add_class("main-content")

        # Check the current theme and add appropriate class
        style_manager = Adw.StyleManager.get_default()
        if not style_manager.get_dark():
            self.toolbar_view.get_style_context().add_class("light")

        # Listen for theme changes
        style_manager.connect("notify::dark", self._on_theme_changed)

        self.set_content(self.toolbar_view)

        self._create_header_bar()
        self._create_content_area()
        self._create_footer_bar()

    def _create_header_bar(self):
        """Create the header bar with menu."""
        menu_items = Gio.Menu.new()

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda a, p: self._presenter.on_about_clicked())
        self.add_action(about_action)
        menu_items.append("About", "win.about")

        # Preferences action
        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", lambda a, p: self._presenter.on_preferences_clicked())
        self.add_action(prefs_action)
        menu_items.append("Preferences", "win.preferences")

        # Create menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu_items)

        # Create theme toggle button
        self.theme_toggle_button = Gtk.Button()
        style_manager = Adw.StyleManager.get_default()

        # Set initial icon based on current theme
        if style_manager.get_dark():
            self.theme_toggle_button.set_icon_name("sun-outline-symbolic")  # Sun icon for light mode
        else:
            self.theme_toggle_button.set_icon_name("moon-outline-symbolic")  # Alternative for dark mode

        self.theme_toggle_button.connect("clicked", self._toggle_theme)
        self.theme_toggle_button.set_tooltip_text("Toggle Theme")

        header_bar = Adw.HeaderBar()
        header_bar.get_style_context().add_class("header-bar")
        header_bar.pack_end(self.theme_toggle_button)
        header_bar.pack_end(menu_button)
        self.toolbar_view.add_top_bar(header_bar)

    def _create_content_area(self):
        """Create the main content area."""
        self.layout_settings_page = LayoutSettingsPage()
        self.layout_settings_page.connect("settings-changed", lambda *args: self._presenter.on_settings_changed())
        self.layout_settings_page.connect(
            "verification-completed", lambda *args: self._presenter.on_verification_completed()
        )
        self.layout_settings_page.connect(
            "instance-launch-requested",
            lambda _, instance_num: self._presenter.on_instance_launch_requested(instance_num),
        )
        self.layout_settings_page.connect(
            "devices-refresh-requested", lambda *args: self._presenter.on_devices_refresh_requested()
        )
        self.toolbar_view.set_content(self.layout_settings_page)

    def _create_footer_bar(self):
        """Create the footer bar with launch button."""
        self.footer_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=0,
            margin_start=12,
            margin_end=12,
            margin_top=6,
            margin_bottom=6,
            homogeneous=False,
            halign=Gtk.Align.END,
        )

        spacer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        spacer.set_hexpand(True)
        self.footer_bar.append(spacer)

        # Launch button
        self.launch_button = Gtk.Button()
        self.launch_button.get_style_context().add_class("launch-button")
        self.launch_button.get_style_context().add_class("play-button-fixed-size")
        self.launch_button.connect("clicked", lambda b: self._presenter.on_launch_clicked())
        self.launch_button.set_sensitive(False)

        # Spinner and label
        self.launch_spinner = Gtk.Spinner()
        self.launch_spinner.set_spinning(False)
        self.launch_label = Gtk.Label(label="Play")

        self.launch_content_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            hexpand=False,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
        )
        self.launch_content_box.append(self.launch_label)
        self.launch_button.set_child(self.launch_content_box)

        self.footer_bar.append(self.launch_button)
        self.toolbar_view.add_bottom_bar(self.footer_bar)

    def get_layout_page(self) -> LayoutSettingsPage:
        """Get the layout settings page."""
        return self.layout_settings_page

    def show_launching_state(self):
        """Update UI to show launching state."""
        self.launch_label.set_label("Starting")
        self.launch_button.set_sensitive(False)
        self.launch_content_box.append(self.launch_spinner)
        self.launch_spinner.start()
        self.layout_settings_page.set_sensitive(False)

    def show_running_state(self):
        """Update UI to show running state."""
        self.launch_label.set_label("Stop")
        self.launch_button.get_style_context().remove_class("launch-button")
        self.launch_button.get_style_context().add_class("stop-button")
        self.launch_spinner.stop()
        if self.launch_spinner.get_parent() == self.launch_content_box:
            self.launch_content_box.remove(self.launch_spinner)
        self.launch_button.set_sensitive(True)
        self.layout_settings_page.set_sensitive(False)
        self.layout_settings_page.set_running_state(True)

    def show_stopping_state(self):
        """Update UI to show stopping state."""
        self.launch_label.set_label("Stopping")
        self.launch_button.set_sensitive(False)
        self.launch_content_box.append(self.launch_spinner)
        self.launch_spinner.start()

    def show_idle_state(self):
        """Update UI to show idle state (ready to launch)."""
        self.launch_label.set_label("Play")
        self.launch_spinner.stop()
        if self.launch_spinner.get_parent() == self.launch_content_box:
            self.launch_content_box.remove(self.launch_spinner)
        self.launch_button.get_style_context().remove_class("stop-button")
        self.launch_button.get_style_context().add_class("launch-button")
        self.layout_settings_page.set_sensitive(True)
        self.layout_settings_page.set_running_state(False)

    def update_launch_button_sensitivity(self, enabled: bool):
        """Update launch button enabled state."""
        self.launch_button.set_sensitive(enabled)

    def show_error(self, message: str, title: str = "Error"):
        """Show an error dialog."""
        dialog = ErrorDialog(self, title, message)
        dialog.present()

    def minimize_window(self):
        """Minimize the window."""
        self.minimize()

    def _toggle_theme(self, button):
        """Toggle between light and dark themes."""
        style_manager = Adw.StyleManager.get_default()
        current_is_dark = style_manager.get_dark()

        # Toggle the theme
        if current_is_dark:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        # Update the icon based on the new theme
        self._update_theme_icon(button)

    def _update_theme_icon(self, button):
        """Update the theme toggle button icon based on current theme."""
        style_manager = Adw.StyleManager.get_default()
        if style_manager.get_dark():
            button.set_icon_name("sun-outline-symbolic")  # Sun icon for light mode
        else:
            button.set_icon_name("moon-outline-symbolic")  # Alternative for dark mode

    def _on_theme_changed(self, style_manager, pspec):
        """Handle theme change."""
        is_dark = style_manager.get_dark()
        if is_dark:
            self.toolbar_view.get_style_context().remove_class("light")
        else:
            self.toolbar_view.get_style_context().add_class("light")

        # Update the theme toggle button icon when theme changes
        if self.theme_toggle_button:
            self._update_theme_icon(self.theme_toggle_button)

    def _on_close_request(self, *args):
        """Handle close request."""
        self._presenter.on_close_requested()
        return True
