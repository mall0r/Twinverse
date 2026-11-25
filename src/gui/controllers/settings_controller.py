"""Application settings and profile management."""

import logging
from typing import Callable

from src.models import PlayerInstanceConfig, Profile, SplitscreenConfig
from src.services import DeviceManager

logger = logging.getLogger(__name__)


class SettingsController:
    """Keeps the profile in sync with the UI and the detected devices."""

    def __init__(self, device_manager: DeviceManager):
        """Initialize the settings controller."""
        self._device_manager = device_manager
        self._profile = Profile.load()
        self._on_change_callbacks: list[Callable[[], None]] = []

    def get_profile(self) -> Profile:
        """Get the current profile."""
        return self._profile

    def save_profile(self):
        """Save the current profile."""
        self._profile.save()
        logger.info("Profile saved.")
        self._notify_change()

    def update_from_ui_data(self, ui_data: dict):
        """
        Update profile from UI data.

        Args:
            ui_data: As returned by the layout page; "selected_players" is
                filtered to the active party while "player_configs" retains
                settings for players outside the current party.
        """
        if "monitor_layouts" in ui_data:
            validated = Profile.model_validate({"monitor_layouts": ui_data["monitor_layouts"]})
            self._profile.monitor_layouts = validated.monitor_layouts
        old_player_configs = self._profile.player_configs[:]

        if "party_players" in ui_data:
            party_players = list(ui_data["party_players"])
            self._profile.party_players = party_players if party_players else None
            self._profile.num_players = len(party_players) if party_players else ui_data["num_players"]
        else:
            self._profile.party_players = None
            self._profile.num_players = ui_data["num_players"]

        self._profile.mode = ui_data["mode"]
        if "layout_order" in ui_data:
            self._profile.layout_order = ui_data["layout_order"]

        if self._profile.mode == "splitscreen" and ui_data["orientation"]:
            self._profile.splitscreen = SplitscreenConfig(ORIENTATION=ui_data["orientation"])

        new_player_configs = list(ui_data["player_configs"])
        party = self._profile.party_indices()
        min_config_count = max(party, default=-1) + 1

        # The page only shows the configured instances, so the settings of the
        # hidden ones are kept and restored when those players return.
        merged = []
        for index in range(max(len(new_player_configs), len(old_player_configs), min_config_count)):
            if index < len(new_player_configs):
                merged.append(new_player_configs[index])
            elif index < len(old_player_configs):
                merged.append(old_player_configs[index])
            else:
                merged.append(PlayerInstanceConfig())
        self._profile.player_configs = merged

        party_set = set(party)
        valid_selected_players = [idx for idx in ui_data["selected_players"] if idx in party_set]
        self._profile.selected_players = valid_selected_players

    def update_preference(self, key: str, value):
        """
        Update a specific preference.

        Args:
            key: A Profile field name; anything else is logged and ignored.
        """
        if hasattr(self._profile, key):
            setattr(self._profile, key, value)
            self.save_profile()
            logger.info(f"Preference '{key}' updated to: {value}")
        else:
            logger.warning(f"Unknown preference key: {key}")

    def get_devices_info(self) -> dict:
        """
        Get information about available devices.

        Returns:
            Dict with "joystick", "mouse", "keyboard", "audio" and "displays".
        """
        input_devices = self._device_manager.get_input_devices()
        return {
            "joystick": input_devices.get("joystick", []),
            "mouse": input_devices.get("mouse", []),
            "keyboard": input_devices.get("keyboard", []),
            "audio": self._device_manager.get_audio_devices(),
            "displays": self._device_manager.get_screen_info(),
        }

    def refresh_devices(self):
        """Refresh device information."""
        logger.info("Refreshing device information...")
        self._device_manager = DeviceManager()

    def register_change_callback(self, callback: Callable[[], None]):
        """
        Register a callback for when settings change.

        Args:
            callback: Called with no arguments after each change.
        """
        self._on_change_callbacks.append(callback)

    def _notify_change(self):
        """Notify all registered callbacks of a change."""
        for callback in self._on_change_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in change callback: {e}", exc_info=True)
