"""
Settings controller module.

This module manages application settings and profile management.
"""

from typing import Callable

from src.core import Logger
from src.models import PlayerInstanceConfig, Profile, SplitscreenConfig
from src.services import DeviceManager


class SettingsController:
    """Manages application settings and profile."""

    def __init__(self, device_manager: DeviceManager, logger: Logger):
        """Initialize the settings controller."""
        self._device_manager = device_manager
        self._logger = logger
        self._profile = Profile.load()
        self._on_change_callbacks: list[Callable[[], None]] = []

    def get_profile(self) -> Profile:
        """Get the current profile."""
        return self._profile

    def save_profile(self):
        """Save the current profile."""
        self._profile.save()
        self._logger.info("Profile saved.")
        self._notify_change()

    def update_from_ui_data(self, ui_data: dict):
        """
        Update profile from UI data.

        Args:
            ui_data: Dictionary containing UI data
        """
        # Store old player configs to preserve settings when number of players changes
        old_player_configs = self._profile.player_configs[:]

        self._profile.num_players = ui_data["num_players"]
        self._profile.mode = ui_data["mode"]

        if self._profile.mode == "splitscreen" and ui_data["orientation"]:
            self._profile.splitscreen = SplitscreenConfig(ORIENTATION=ui_data["orientation"])
        else:
            self._profile.splitscreen = None

        # Update player configs, preserving old configs when possible
        new_player_configs = ui_data["player_configs"]

        # If we have more slots than new configs, extend with preserved old configs or defaults
        while len(new_player_configs) < self._profile.num_players:
            if len(new_player_configs) < len(old_player_configs):
                # Use old config if available
                new_player_configs.append(old_player_configs[len(new_player_configs)])
            else:
                # Add default config
                new_player_configs.append(PlayerInstanceConfig())

        self._profile.player_configs = new_player_configs

        # Filter selected_players to only include valid indices based on the new number of players
        valid_selected_players = [idx for idx in ui_data["selected_players"] if 0 <= idx < self._profile.num_players]
        self._profile.selected_players = valid_selected_players

        # Always enable KWin script
        self._profile.enable_kwin_script = True

    def update_preference(self, key: str, value):
        """
        Update a specific preference.

        Args:
            key: The preference key
            value: The preference value
        """
        if hasattr(self._profile, key):
            setattr(self._profile, key, value)
            self.save_profile()
            self._logger.info(f"Preference '{key}' updated to: {value}")
        else:
            self._logger.warning(f"Unknown preference key: {key}")

    def get_devices_info(self) -> dict:
        """
        Get information about available devices.

        Returns:
            Dictionary with device information
        """
        return {
            "joystick": self._device_manager.get_input_devices().get("joystick", []),
            "mouse": self._device_manager.get_input_devices().get("mouse", []),
            "keyboard": self._device_manager.get_input_devices().get("keyboard", []),
            "audio": self._device_manager.get_audio_devices(),
            "displays": self._device_manager.get_screen_info(),
        }

    def refresh_devices(self):
        """Refresh device information."""
        self._logger.info("Refreshing device information...")
        # Force refresh by recreating device manager
        self._device_manager = DeviceManager()

    def register_change_callback(self, callback: Callable[[], None]):
        """
        Register a callback for when settings change.

        Args:
            callback: Function to call when settings change
        """
        self._on_change_callbacks.append(callback)

    def _notify_change(self):
        """Notify all registered callbacks of a change."""
        for callback in self._on_change_callbacks:
            try:
                callback()
            except Exception as e:
                self._logger.error(f"Error in change callback: {e}", exc_info=True)
