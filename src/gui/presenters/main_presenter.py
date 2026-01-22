"""
Main presenter module.

This module mediates between the view (window) and controllers.
"""

import os

from gi.repository import Adw, GLib, Gtk

from src.core import Logger
from src.gui.controllers import (
    LaunchController,
    SettingsController,
    VerificationController,
)
from src.gui.utils import ErrorHandler
from src.gui.windows import MainWindow, PreferencesWindow
from src.services import DeviceManager, InstanceService, KdeManager, SteamVerifier


class MainPresenter:
    """Mediator between the view and controllers."""

    def __init__(self, application, logger: Logger):
        """Initialize the main presenter."""
        self._app = application
        self._logger = logger

        # Initialize services
        self._kde_manager = KdeManager(self._logger)
        self._instance_service = InstanceService(logger=self._logger, kde_manager=self._kde_manager)
        self._steam_verifier = SteamVerifier(self._logger)
        self._device_manager = DeviceManager()

        # Initialize controllers
        self._launch_controller = LaunchController(self._instance_service, self._kde_manager, self._logger)
        self._verification_controller = VerificationController(self._steam_verifier, self._logger)
        self._settings_controller = SettingsController(self._device_manager, self._logger)

        # Create window
        self.window = MainWindow(application, self)

        # Load initial data
        self._load_initial_data()

    def _load_initial_data(self):
        """Load initial data into the UI."""
        profile = self._settings_controller.get_profile()
        devices_info = self._settings_controller.get_devices_info()

        # Run initial verifications
        self._verification_controller.verify_all_instances(
            profile.num_players, on_each_complete=lambda i, verified: None  # Silent initial verification
        )

        verification_statuses = self._verification_controller.get_all_statuses()

        # Load into UI
        layout_page = self.window.get_layout_page()
        layout_page.load_data(profile, devices_info, verification_statuses)

        # Update button state
        self._update_launch_button_state()

    def on_launch_clicked(self):
        """Handle launch button clicked."""
        if self._launch_controller.is_running():
            self._on_stop_requested()
        else:
            self._on_launch_requested()

    def on_settings_changed(self):
        """Handle settings changed in UI."""
        # Get the current number of players before saving
        layout_page = self.window.get_layout_page()
        old_num_players = len(layout_page.player_rows)

        # Get UI data first to check if number of players changed
        ui_data = layout_page.get_data()
        new_num_players = ui_data["num_players"]

        # If the number of players changed, reload the UI first to update player_rows
        if old_num_players != new_num_players:
            # Update the profile temporarily to reflect new number of players
            profile = self._settings_controller.get_profile()
            profile.num_players = new_num_players

            # Reload UI to update player_rows
            devices_info = self._settings_controller.get_devices_info()
            verification_statuses = self._verification_controller.get_all_statuses()
            layout_page.load_data(profile, devices_info, verification_statuses)

            # Get fresh UI data after UI update
            ui_data = layout_page.get_data()

        # Now save the current settings with updated UI data
        self._settings_controller.update_from_ui_data(ui_data)
        self._settings_controller.save_profile()

        # Reload UI again to ensure everything is consistent (especially if other settings changed)
        if old_num_players != new_num_players:
            profile = self._settings_controller.get_profile()
            devices_info = self._settings_controller.get_devices_info()
            verification_statuses = self._verification_controller.get_all_statuses()
            layout_page.load_data(profile, devices_info, verification_statuses)
        else:
            # Just run verifications if the number of players didn't change
            self._run_all_verifications()

        self._update_launch_button_state()

    def on_verification_completed(self):
        """Handle verification completed."""
        self._update_launch_button_state()

    def on_instance_launch_requested(self, instance_num: int):
        """Handle single instance launch request."""
        profile = self._settings_controller.get_profile()
        layout_page = self.window.get_layout_page()
        player_rows = layout_page.player_rows

        if instance_num >= len(player_rows):
            return

        player_row = player_rows[instance_num]

        if player_row._is_running:
            # Stop only this specific instance
            self._launch_controller.terminate_single_instance(
                instance_num, on_complete=lambda: self._on_single_instance_stopped(instance_num)
            )
        else:
            # Launch without verification (different from main Play button)
            self._logger.info(f"Launch requested for instance {instance_num} (no verification required).")

            # Save current settings
            self._save_current_settings()

            # Update UI to show launching state for this specific instance
            player_row.set_running_state(True)
            player_row._update_button_state()

            # Launch this specific instance using the same setup flow as the main Play button
            # but disable gamescope for individual instances and skip verification
            self._logger.info(f"Initiating launch of instance {instance_num}...")

            # Setup KDE if enabled for this instance (same as main Play button)
            if profile.enable_kwin_script:
                self._logger.info("Starting KDE script setup...")
                self._kde_manager.start_kwin_script(profile)

            # Launch only this specific instance with gamescope disabled
            try:
                self._instance_service.launch_instance(profile, instance_num, use_gamescope_override=False)
                self._logger.info(f"Instance {instance_num} launch initiated successfully (gamescope disabled).")

                # Update UI to reflect that this instance is now running
                GLib.idle_add(lambda: self._on_single_instance_launched(instance_num))
            except Exception as e:
                self._logger.error(f"Failed to launch instance {instance_num}: {e}")
                self._logger.exception("Exception details:")
                error_msg = ErrorHandler.format_error(e)
                GLib.idle_add(self.window.show_error, error_msg)
                # Reset the button state to previous state
                player_row.set_running_state(False)
                player_row._update_button_state()

    def on_preferences_clicked(self):
        """Handle preferences menu clicked."""
        profile = self._settings_controller.get_profile()
        prefs_window = PreferencesWindow(self.window, profile, self._on_preference_changed)
        prefs_window.present()

    def on_about_clicked(self):
        """Handle about menu clicked."""
        version = self._get_version()
        about = Adw.AboutDialog(
            application_name="Twinverse",
            application_icon="io.github.mall0r.Twinverse",
            developer_name="Messias Junior (mall0r)",
            version=version,
            developers=["Messias Junior"],
            website="https://github.com/mall0r/Twinverse/blob/main/README.md",
            issue_url="https://github.com/mall0r/Twinverse/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=(
                "Twinverse is a tool for Linux/SteamOS that allows you to create and manage multiple "
                "instances of gamescope and steam simultaneously. Twinverse uses Bubblewrap (bwrap), "
                "a low-level Linux sandboxing tool, to isolate each Steam Client instance."
            ),
            support_url="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.md",
        )

        about.add_link("Contributing", "https://github.com/mall0r/Twinverse/blob/main/CONTRIBUTING.md")
        about.add_link("Donate", "https://ko-fi.com/mallor")
        about.present(parent=self.window)

    def on_close_requested(self):
        """Handle window close request."""
        self.window.set_sensitive(False)

        # Stop all instances before closing
        self._launch_controller.stop_instances(on_complete=lambda: GLib.idle_add(self._app.quit))

    def on_devices_refresh_requested(self):
        """Handle devices refresh request."""
        self._logger.info("Refreshing devices...")
        self._settings_controller.refresh_devices()
        devices_info = self._settings_controller.get_devices_info()

        layout_page = self.window.get_layout_page()
        layout_page.update_devices_info(devices_info)

    def _on_launch_requested(self):
        """Handle launch request."""
        self._logger.info("Launch requested by user.")

        # Save current settings
        self._save_current_settings()

        # Run verifications
        self._run_all_verifications()

        # Check if any players are selected
        layout_page = self.window.get_layout_page()
        selected_players = layout_page.get_selected_players()

        if not selected_players:
            self._logger.warning("No instances selected to launch.")
            self.window.show_error("No instances selected to launch.")
            return

        self._logger.info(f"Selected players for launch: {selected_players}")

        # Update profile with selected players
        profile = self._settings_controller.get_profile()
        profile.selected_players = selected_players
        self._settings_controller.save_profile()

        # Update UI to launching state
        self.window.show_launching_state()

        # Schedule window minimization
        GLib.timeout_add(5000, self.window.minimize_window)

        # Launch instances
        self._logger.info("Initiating launch of instances...")
        self._launch_controller.launch_instances(
            profile,
            on_progress=self._on_launch_progress,
            on_complete=self._on_launch_complete,
            on_error=self._on_launch_error,
        )

    def _on_stop_requested(self):
        """Handle stop request."""
        self.window.show_stopping_state()

        self._launch_controller.stop_instances(on_complete=self._on_stop_complete)

    def _on_launch_progress(self, instance_num: int):
        """Handle launch progress update."""
        self._logger.info(f"Launched instance {instance_num}")
        # Update UI to reflect that this instance is now running
        layout_page = self.window.get_layout_page()
        if 0 <= instance_num < len(layout_page.player_rows):
            player_row = layout_page.player_rows[instance_num]
            player_row.set_running_state(True)

    def _on_launch_complete(self):
        """Handle launch complete."""
        GLib.idle_add(self.window.show_running_state)

    def _on_launch_error(self, error: Exception):
        """Handle launch error."""
        self._logger.error(f"Launch error: {error}")
        self._logger.exception("Exception details:")
        error_msg = ErrorHandler.format_error(error)
        GLib.idle_add(self.window.show_error, error_msg)
        GLib.idle_add(self._restore_after_failed_launch)

    def _on_stop_complete(self):
        """Handle stop complete."""
        GLib.idle_add(self.window.show_idle_state)
        GLib.idle_add(self._run_all_verifications)
        GLib.idle_add(self._update_launch_button_state)

    def _on_single_instance_launched(self, instance_num: int):
        """Handle single instance launched."""
        # Update the specific player row to reflect running state
        layout_page = self.window.get_layout_page()
        if 0 <= instance_num < len(layout_page.player_rows):
            player_row = layout_page.player_rows[instance_num]
            player_row.set_running_state(True)

        GLib.idle_add(self._verify_instance, instance_num)

    def _on_single_instance_stopped(self, instance_num: int):
        """Handle single instance stopped."""
        # Update the specific player row to reflect stopped state
        layout_page = self.window.get_layout_page()
        if 0 <= instance_num < len(layout_page.player_rows):
            player_row = layout_page.player_rows[instance_num]
            player_row.set_running_state(False)

        GLib.idle_add(self._verify_instance, instance_num)

    def _on_single_instance_error(self, instance_num: int, error: Exception):
        """Handle single instance error."""
        self._logger.error(f"Error in instance {instance_num}: {error}")
        error_msg = ErrorHandler.format_error(error)
        GLib.idle_add(self.window.show_error, error_msg)

    def _on_preference_changed(self, key: str, value):
        """Handle preference changed."""
        self._settings_controller.update_preference(key, value)

    def _save_current_settings(self):
        """Save current settings from UI."""
        layout_page = self.window.get_layout_page()
        ui_data = layout_page.get_data()
        self._settings_controller.update_from_ui_data(ui_data)
        self._settings_controller.save_profile()

    def _run_all_verifications(self):
        """Run verifications for all instances."""
        profile = self._settings_controller.get_profile()
        layout_page = self.window.get_layout_page()

        self._verification_controller.verify_all_instances(
            profile.num_players,
            on_each_complete=lambda i, verified: layout_page.update_verification_status(i, verified),
        )

    def _verify_instance(self, instance_num: int):
        """Verify a specific instance."""
        is_verified = self._verification_controller.verify_instance(instance_num)
        layout_page = self.window.get_layout_page()
        layout_page.update_verification_status(instance_num, is_verified)

    def _update_launch_button_state(self):
        """Update launch button enabled state."""
        layout_page = self.window.get_layout_page()
        selected_players = layout_page.get_selected_players()

        if not selected_players:
            self.window.update_launch_button_sensitivity(False)
            return

        # Check if all selected players are verified
        all_verified = all(self._verification_controller.get_verification_status(p) for p in selected_players)

        self.window.update_launch_button_sensitivity(all_verified)

    def _restore_after_failed_launch(self):
        """Restore UI after a failed launch."""
        self.window.show_idle_state()
        self._run_all_verifications()
        self._update_launch_button_state()

    def _get_version(self) -> str:
        """Get application version."""
        try:
            version_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "version"
            )
            with open(version_file, "r") as f:
                return f.read().strip()
        except Exception:
            return "Unknown"
