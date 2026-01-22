#!/usr/bin/env python3
"""Test script to verify UI update fixes."""

import os
import sys

from src.core.config import Config
from src.core.logger import Logger
from src.gui.controllers.settings_controller import SettingsController
from src.models import Profile
from src.services.device_manager import DeviceManager

# Adicionando o caminho src para que os imports funcionem corretamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_profile_preservation():
    """Test that profile settings are preserved when number of players changes."""
    print("Testing profile preservation when number of players changes...")

    # Create a logger
    logger = Logger("test", Config.LOG_DIR)

    # Create a device manager
    device_manager = DeviceManager()

    # Create settings controller
    controller = SettingsController(device_manager, logger)

    # Create an initial profile with 2 players and specific settings
    profile = Profile()
    profile.num_players = 2
    profile.player_configs[0].physical_device_id = "/dev/input/js0"
    profile.player_configs[0].grab_input_devices = True
    profile.player_configs[0].audio_device_id = "alsa_output.pci-0000_00_1f.3.analog-stereo"
    profile.player_configs[1].physical_device_id = "/dev/input/js1"
    profile.player_configs[1].grab_input_devices = False

    # Save the profile
    controller._profile = profile
    controller.save_profile()

    print(f"Initial profile: {profile.num_players} players")
    print(
        f"Player 0: device={profile.player_configs[0].physical_device_id}, grab={profile.player_configs[0].grab_input_devices}"
    )
    print(
        f"Player 1: device={profile.player_configs[1].physical_device_id}, grab={profile.player_configs[1].grab_input_devices}"
    )

    # Simulate UI data with 3 players
    ui_data = {
        "num_players": 3,
        "mode": "splitscreen",
        "orientation": "horizontal",
        "player_configs": [
            profile.player_configs[0],  # Keep first player config
            profile.player_configs[1],  # Keep second player config
            # Third player will be default
        ],
        "selected_players": [0, 1, 2],
    }

    # Update from UI data
    controller.update_from_ui_data(ui_data)

    # Check the updated profile
    updated_profile = controller.get_profile()
    print("\nAfter update to 3 players:")
    print(f"Num players: {updated_profile.num_players}")
    print(f"Player configs count: {len(updated_profile.player_configs)}")

    for i, config in enumerate(updated_profile.player_configs):
        print(f"Player {i}: device={config.physical_device_id}, grab={config.grab_input_devices}")

    # Now simulate reducing back to 2 players
    ui_data_reduce = {
        "num_players": 2,
        "mode": "splitscreen",
        "orientation": "horizontal",
        "player_configs": [
            updated_profile.player_configs[0],  # Keep first player config
            updated_profile.player_configs[1],  # Keep second player config
        ],
        "selected_players": [0, 1],
    }

    controller.update_from_ui_data(ui_data_reduce)

    reduced_profile = controller.get_profile()
    print("\nAfter reducing to 2 players:")
    print(f"Num players: {reduced_profile.num_players}")
    print(f"Player configs count: {len(reduced_profile.player_configs)}")

    for i, config in enumerate(reduced_profile.player_configs):
        print(f"Player {i}: device={config.physical_device_id}, grab={config.grab_input_devices}")

    print("\nTest completed successfully!")


def test_settings_controller():
    """Test the settings controller functionality."""
    print("\nTesting settings controller...")

    logger = Logger("test", Config.LOG_DIR)
    device_manager = DeviceManager()
    controller = SettingsController(device_manager, logger)

    # Test getting initial profile
    profile = controller.get_profile()
    print(f"Initial profile has {profile.num_players} players")

    # Test updating from UI data
    ui_data = {
        "num_players": 4,
        "mode": "fullscreen",
        "orientation": None,
        "player_configs": [
            # Add 4 player configs
        ],
        "selected_players": [0, 1, 2, 3],
    }

    # Create some dummy configs
    for i in range(4):
        from src.models import PlayerInstanceConfig

        config = PlayerInstanceConfig()
        config.physical_device_id = f"/dev/input/js{i}"
        config.grab_input_devices = i % 2 == 0  # Alternate grab input
        ui_data["player_configs"].append(config)

    controller.update_from_ui_data(ui_data)
    updated_profile = controller.get_profile()

    print(f"After update: {updated_profile.num_players} players")
    for i, config in enumerate(updated_profile.player_configs):
        print(f"  Player {i}: device={config.physical_device_id}, grab={config.grab_input_devices}")

    print("Settings controller test completed!")


if __name__ == "__main__":
    test_profile_preservation()
    test_settings_controller()
    print("\nAll tests completed!")
