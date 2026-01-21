"""
GUI module for the Twinverse application.

This module provides the main GUI window and application classes for the
Twinverse application.
"""

import os
import sys
import threading
import time

import gi
from gi.repository import Adw, Gio, GLib, Gtk

from src.core import Config, Logger, Utils
from src.core.exceptions import DependencyError, TwinverseError, VirtualDeviceError
from src.gui.layout_editor import LayoutSettingsPage
from src.models import Profile
from src.services import InstanceService, KdeManager

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class TwinverseWindow(Adw.ApplicationWindow):
    """Main window class for the Twinverse GUI application."""

    def __init__(self, *args, **kwargs):
        """Initialize the main window and set up the UI."""
        super().__init__(*args, **kwargs)
        self.set_title("Twinverse")
        self.set_default_size(800, 600)

        self.logger = Logger("Twinverse-GUI", Config.LOG_DIR, reset=True)
        self.profile = Profile.load()
        self.kde_manager = KdeManager(self.logger)
        self.instance_service = InstanceService(logger=self.logger, kde_manager=self.kde_manager)
        self._launch_thread = None
        self._cancel_launch_event = threading.Event()
        self._is_running = False
        self.utils = Utils()
        self._build_ui()
        self._update_launch_button_state()
        self.connect("close-request", self.on_close_request)

    def _show_error_dialog(self, message, title="Error"):
        """Show an error dialog with the given message and title."""
        dialog = Adw.MessageDialog(transient_for=self, modal=True, title=title, body=message)
        dialog.add_response("ok", "OK")
        dialog.present()

    def _handle_launch_error(self, error: Exception):
        """Handle launch errors with appropriate messaging."""
        error_msg = self._get_error_message(error)
        self.instance_service.terminate_all()
        GLib.idle_add(self._show_error_dialog, error_msg)
        GLib.idle_add(self._restore_ui_after_failed_launch)

    def _get_error_message(self, error: Exception) -> str:
        """Generate appropriate error message based on error type."""
        # Check for specific exception types first
        if isinstance(error, DependencyError):
            # Handle dependency errors
            return f"Missing dependency: {error}"
        elif isinstance(error, FileNotFoundError):
            # Handle file not found errors
            filename = getattr(error, "filename", None)
            if filename:
                return f"Required command '{filename}' not found. Please install the missing dependency."
            else:
                return f"Required file or command not found: {error}"
        elif isinstance(error, OSError):
            # Handle OS-level errors like "No such file or directory" (errno 2)
            if hasattr(error, "errno") and error.errno == 2:  # ENOENT
                filename = getattr(error, "filename", None)
                if filename:
                    return f"Required command '{filename}' not found. Please install the missing dependency."
                else:
                    return f"Required file or command not found: {error}"
            else:
                return f"System error: {error}"
        elif isinstance(error, VirtualDeviceError):
            # Handle virtual device errors
            return f"Virtual device error: {error}"
        elif isinstance(error, TwinverseError):
            # Handle other specific errors
            return f"Twinverse error: {error}"
        else:
            return f"Could not launch: {error}"

    def _build_ui(self):
        self.toolbar_view = Adw.ToolbarView()
        self.toolbar_view.get_style_context().add_class("main-content")
        self.set_content(self.toolbar_view)

        # Create menu items
        menu_items = Gio.Menu.new()

        # Add About menu item
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.show_about_dialog)
        self.add_action(about_action)
        menu_items.append("About", "win.about")

        # Add Preferences menu item
        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self.show_preferences_dialog)
        self.add_action(prefs_action)
        menu_items.append("Preferences", "win.preferences")

        # Create menu button with hamburger icon
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu_items)

        header_bar = Adw.HeaderBar()
        header_bar.get_style_context().add_class("header-bar")
        header_bar.pack_end(menu_button)  # Pack menu button to the end (right side)
        self.toolbar_view.add_top_bar(header_bar)

        self.layout_settings_page = LayoutSettingsPage(self.profile, self.logger)
        self.layout_settings_page.connect("settings-changed", self._trigger_auto_save)
        self.layout_settings_page.connect("verification-completed", self._update_launch_button_state)
        self.toolbar_view.set_content(self.layout_settings_page)

        # Footer Bar for Play/Stop buttons
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

        self.launch_button = Gtk.Button()
        self.launch_button.get_style_context().add_class("launch-button")
        self.launch_button.get_style_context().add_class("play-button-fixed-size")
        self.launch_button.connect("clicked", self.on_launch_clicked)
        self.launch_button.set_sensitive(False)

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

    def _trigger_auto_save(self, *args):
        updated_profile = self.layout_settings_page.get_updated_data()
        self.profile = updated_profile
        self.profile.save()
        self.logger.info("Profile auto-saved.")
        self.layout_settings_page._run_all_verifications()
        self._update_launch_button_state()

    def _update_launch_button_state(self, *args):
        selected_players = self.layout_settings_page.get_selected_players()
        if not selected_players:
            self.launch_button.set_sensitive(False)
            return

        all_verified = all(self.layout_settings_page.get_instance_verification_status(p) for p in selected_players)
        self.launch_button.set_sensitive(all_verified)

    def _launch_worker(self):
        selected_players = self.profile.selected_players
        self.logger.info(f"Launch worker started for players: {selected_players}")

        try:
            for instance_num in selected_players:
                if self._cancel_launch_event.is_set():
                    self.logger.info("Launch sequence cancelled by user.")
                    break
                self.logger.info(f"Worker launching instance {instance_num}...")
                self.instance_service.launch_instance(self.profile, instance_num)
                time.sleep(5)

            if not self._cancel_launch_event.is_set():
                GLib.idle_add(self._on_launch_finished)

        except Exception as e:
            self._handle_launch_error(e)

    def _restore_ui_after_failed_launch(self):
        self.kde_manager.restore_panel_states()
        self.launch_label.set_label("Play")
        self.launch_spinner.stop()
        if self.launch_spinner.get_parent() == self.launch_content_box:
            self.launch_content_box.remove(self.launch_spinner)
        self.layout_settings_page.set_sensitive(True)
        self.layout_settings_page.set_running_state(False)
        self._is_running = False
        self._launch_thread = None
        self._cancel_launch_event.clear()
        self._update_launch_button_state()

    def _on_launch_finished(self):
        self.logger.info("Launch worker finished.")
        if not self._cancel_launch_event.is_set():
            self.launch_label.set_label("Stop")
            self.launch_button.get_style_context().remove_class("launch-button")
            self.launch_button.get_style_context().add_class("stop-button")
            self.layout_settings_page.set_sensitive(False)
            self.layout_settings_page.set_running_state(True)
            self._is_running = True

        self.launch_spinner.stop()
        if self.launch_spinner.get_parent() == self.launch_content_box:
            self.launch_content_box.remove(self.launch_spinner)
        self.launch_button.set_sensitive(True)
        self._launch_thread = None
        self._cancel_launch_event.clear()

    def on_launch_clicked(self, button):
        """Handle the launch button click event."""
        if self._is_running:
            self.on_stop_clicked()
            return

        self.layout_settings_page._run_all_verifications()
        selected_players = self.layout_settings_page.get_selected_players()
        if not selected_players:
            self._show_error_dialog("No instances selected to launch.")
            return

        self.profile.selected_players = selected_players
        self.profile.save()

        if self.profile.enable_kwin_script:
            self.kde_manager.start_kwin_script(self.profile)

        self.kde_manager.save_panel_states()
        self.kde_manager.set_panels_dodge_windows()

        self.launch_label.set_label("Starting")
        self.launch_button.set_sensitive(False)
        self.launch_content_box.append(self.launch_spinner)
        self.launch_spinner.start()
        self.layout_settings_page.set_sensitive(False)

        # Minimize the GUI after 2 seconds
        GLib.timeout_add(2000, self.minimize_window)

        self._cancel_launch_event.clear()
        self._launch_thread = threading.Thread(target=self._launch_worker)
        self._launch_thread.start()

    def minimize_window(self):
        """Minimize the main window."""
        self.minimize()
        return False  # Return False to prevent repeated calls

    def on_stop_clicked(self):
        """Handle the stop button click event."""
        if self._launch_thread and self._launch_thread.is_alive():
            self.logger.info("Cancelling in-progress launch...")
            self._cancel_launch_event.set()

        self.launch_label.set_label("Stopping")
        self.launch_button.set_sensitive(False)
        self.launch_content_box.append(self.launch_spinner)
        self.launch_spinner.start()

        stop_thread = threading.Thread(target=self._stop_worker)
        stop_thread.start()

    def _stop_worker(self):
        self.instance_service.terminate_all()
        GLib.idle_add(self._on_termination_finished)

    def _on_termination_finished(self):
        self.logger.info("Termination worker finished.")
        self.launch_label.set_label("Play")
        self.launch_button.set_sensitive(True)
        self.launch_spinner.stop()
        if self.launch_spinner.get_parent() == self.launch_content_box:
            self.launch_content_box.remove(self.launch_spinner)
        self.launch_button.get_style_context().remove_class("stop-button")
        self.launch_button.get_style_context().add_class("launch-button")
        self.layout_settings_page.set_sensitive(True)
        self.layout_settings_page.set_running_state(False)
        self.layout_settings_page._run_all_verifications()
        self._update_launch_button_state()
        self._is_running = False

    def show_about_dialog(self, action, param):
        """Show the about dialog."""
        # Read version from the version file
        # The version file is guaranteed to be available both in development and Flatpak environments
        version_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "version")
        with open(version_file_path, "r") as f:
            version = f.read().strip()

        about = Adw.AboutDialog(
            application_name="Twinverse",
            application_icon="io.github.mall0r.Twinverse",  # This should match your application ID
            developer_name="Messias Junior (mall0r)",
            version=version,
            developers=["mall0r"],
            website="https://github.com/mall0r/Twinverse/blob/main/README.md",
            issue_url="https://github.com/mall0r/Twinverse/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=(
                "A tool for Linux/SteamOS that allows you to create and manage multiple instances of gamescope and steam simultaneously. "
                "Twinverse uses Bubblewrap (bwrap), a low-level Linux sandboxing tool, to isolate each Steam Client instance."
            ),
            artists=["mall0r"],
            support_url="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.md",
        )
        # Add additional links using the proper API
        about.add_link("Contributing", "https://github.com/mall0r/Twinverse/blob/main/CONTRIBUTING.md")
        about.add_link("Donate", "https://ko-fi.com/mallor")

        # Get the original comments and append the disclaimer with clickable license link
        disclaimer_text = (
            "Twinverse is an independent open-source project and is not affiliated with, "
            "endorsed by, or in any way officially connected to Valve Corporation or Steam.\n\n"
            "This tool acts as an orchestration layer that leverages sandboxing technologies "
            "(bubblewrap) to run multiple isolated instances of the official Steam client. "
            "Twinverse does not modify, patch, reverse engineer, or alter any Steam files "
            "or its normal operation. All Steam instances launched by this tool are the "
            "official, unmodified versions provided by Valve.\n\n"
            "Users are solely responsible for complying with the terms of the Steam Subscriber Agreement.\n\n"
            "This application comes without any warranty whatsoever. "
            'See the <a href="https://www.gnu.org/licenses/gpl-3.0.html">GNU General Public License, version 3 or later</a> for more details.'
        )

        # Set the combined comments with markup
        about.set_license(disclaimer_text)

        # Show the about dialog
        about.present(parent=self)

    def show_preferences_dialog(self, action, param):
        """Show the preferences dialog."""
        # Create preferences window
        prefs_window = Adw.PreferencesWindow()
        prefs_window.set_transient_for(self)
        prefs_window.set_modal(True)
        prefs_window.set_title("Preferences")

        # Create preferences page
        prefs_page = Adw.PreferencesPage()
        prefs_page.set_title("Options")
        prefs_page.set_icon_name("preferences-other-symbolic")

        # Create preferences group
        prefs_group = Adw.PreferencesGroup(
            title="Advanced Options", description="Only modify if you know what you are doing"
        )

        # Create SteamDeck tag row (this already contains a switch)
        steamdeck_row = Adw.SwitchRow()
        steamdeck_row.set_title("SteamDeck Tag")
        steamdeck_row.set_subtitle("Add --mangoapp to Gamescope and -steamdeck to Steam command when enabled")
        steamdeck_row.set_active(self.profile.use_steamdeck_tag)
        steamdeck_row.connect("notify::active", self._on_steamdeck_tag_toggled_from_row)

        # Add SteamDeck row to group
        prefs_group.add(steamdeck_row)

        # Create Gamescope toggle row
        gamescope_row = Adw.SwitchRow()
        gamescope_row.set_title("Use Gamescope")
        gamescope_row.set_subtitle("Disable to run Steam directly in bwrap without Gamescope")
        gamescope_row.set_active(self.profile.use_gamescope)
        gamescope_row.connect("notify::active", self._on_gamescope_toggled_from_preferences)

        # Add Gamescope row to group
        prefs_group.add(gamescope_row)

        # Create Gamescope WSI toggle row
        gamescope_wsi_row = Adw.SwitchRow()
        gamescope_wsi_row.set_title("Enable Gamescope WSI")
        gamescope_wsi_row.set_subtitle("Enable Gamescope Wayland Support Interface (WSI)")
        gamescope_wsi_row.set_active(self.profile.enable_gamescope_wsi)
        gamescope_wsi_row.connect("notify::active", self._on_gamescope_wsi_toggled_from_preferences)

        # Add Gamescope WSI row to group
        prefs_group.add(gamescope_wsi_row)

        # Add group to page
        prefs_page.add(prefs_group)

        # Add page to window
        prefs_window.add(prefs_page)

        # Show the preferences window
        prefs_window.present()

    def _on_steamdeck_tag_toggled(self, switch, state):
        """Handle SteamDeck tag switch toggled event."""
        self.profile.use_steamdeck_tag = state
        self.profile.save()
        self.logger.info(f"SteamDeck tag option {'enabled' if state else 'disabled'}")

    def _on_steamdeck_tag_toggled_from_row(self, switch_row, pspec):
        """Handle SteamDeck tag switch toggled event from SwitchRow."""
        state = switch_row.get_active()
        self.profile.use_steamdeck_tag = state
        self.profile.save()
        self.logger.info(f"SteamDeck tag option {'enabled' if state else 'disabled'}")

    def _on_gamescope_toggled_from_preferences(self, switch_row, pspec):
        """Handle Gamescope toggle switch toggled event from SwitchRow."""
        state = switch_row.get_active()
        self.profile.use_gamescope = state
        self.profile.save()
        self.logger.info(f"Gamescope option {'enabled' if state else 'disabled'}")

    def _on_gamescope_wsi_toggled_from_preferences(self, switch_row, pspec):
        """Handle Gamescope WSI toggle switch toggled event from SwitchRow."""
        state = switch_row.get_active()
        self.profile.enable_gamescope_wsi = state
        self.profile.save()
        self.logger.info(f"Gamescope WSI option {'enabled' if state else 'disabled'}")

    def on_close_request(self, *args):
        """Handle the close request event."""
        self.logger.info("Close request received. Starting shutdown procedure.")
        self.set_sensitive(False)
        shutdown_thread = threading.Thread(target=self._shutdown_worker)
        shutdown_thread.start()
        return True

    def _shutdown_worker(self):
        self.logger.info("Shutdown worker started.")
        self._stop_worker()
        GLib.idle_add(self.get_application().quit)


class TwinverseApplication(Adw.Application):
    """Main application class for the Twinverse GUI application."""

    def __init__(self, **kwargs):
        """Initialize the application and set up resources."""
        super().__init__(application_id="io.github.mall0r.Twinverse", **kwargs)
        self.base_path = Utils.get_base_path()

        # Load resources
        resource_path = self.base_path / "res" / "compiled.gresource"
        if resource_path.exists():
            resources = Gio.Resource.load(str(resource_path))
            Gio.Resource._register(resources)

        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        """Handle the application activation event."""
        self.win = TwinverseWindow(application=app)

        css_provider = Gtk.CssProvider()
        css_path = self.base_path / "res" / "styles" / "style.css"
        if css_path.exists():
            css_provider.load_from_path(str(css_path))
            Gtk.StyleContext.add_provider_for_display(
                self.win.get_display(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        self.win.present()


def run_gui():
    """Launch the GUI application."""
    os.environ["GSK_RENDERER"] = "gl"
    # Unset the old "prefer dark theme" setting to avoid Adwaita warnings
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-application-prefer-dark-theme", False)

    # Set the dark theme BEFORE instantiating the app
    style_manager = Adw.StyleManager.get_default()
    style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    app = TwinverseApplication()
    app.run(sys.argv)
