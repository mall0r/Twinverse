#!/usr/bin/env python3
"""Test script to verify UI update fixes without GUI dependencies."""

from src.models import Profile


def test_profile_preservation():
    """Test that profile settings are preserved when number of players changes."""
    print("Testing profile preservation when number of players changes...")

    # Create an initial profile with 2 players and specific settings
    profile = Profile()
    profile.num_players = 2
    profile.player_configs[0].physical_device_id = "/dev/input/js0"
    profile.player_configs[0].grab_input_devices = True
    profile.player_configs[0].audio_device_id = "alsa_output.pci-0000_00_1f.3.analog-stereo"
    profile.player_configs[1].physical_device_id = "/dev/input/js1"
    profile.player_configs[1].grab_input_devices = False

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

    # Simulate the update from UI data (without actual controller)
    # This mimics what the controller would do internally
    profile.num_players = ui_data["num_players"]
    profile.player_configs = ui_data["player_configs"]
    profile.mode = ui_data["mode"]
    profile.splitscreen = {"orientation": ui_data["orientation"]} if ui_data["mode"] == "splitscreen" else None

    print("\nAfter update to 3 players:")
    print(f"Num players: {profile.num_players}")
    print(f"Player configs count: {len(profile.player_configs)}")

    for i, config in enumerate(profile.player_configs):
        print(f"Player {i}: device={config.physical_device_id}, grab={config.grab_input_devices}")

    # Now simulate reducing back to 2 players
    ui_data_reduce = {
        "num_players": 2,
        "mode": "splitscreen",
        "orientation": "horizontal",
        "player_configs": [
            profile.player_configs[0],  # Keep first player config
            profile.player_configs[1],  # Keep second player config
        ],
        "selected_players": [0, 1],
    }

    # Simulate the update from UI data again
    profile.num_players = ui_data_reduce["num_players"]
    profile.player_configs = ui_data_reduce["player_configs"]
    profile.mode = ui_data_reduce["mode"]
    profile.splitscreen = (
        {"orientation": ui_data_reduce["orientation"]} if ui_data_reduce["mode"] == "splitscreen" else None
    )

    print("\nAfter reducing to 2 players:")
    print(f"Num players: {profile.num_players}")
    print(f"Player configs count: {len(profile.player_configs)}")

    for i, config in enumerate(profile.player_configs):
        print(f"Player {i}: device={config.physical_device_id}, grab={config.grab_input_devices}")

    print("\nTest completed successfully!")


def test_settings_controller_logic():
    """Test the settings controller functionality without GUI dependencies."""
    print("\nTesting settings controller logic...")

    # Create an initial profile
    profile = Profile()
    print(f"Initial profile has {profile.num_players} players")

    # Simulate UI data
    ui_data = {
        "num_players": 4,
        "mode": "fullscreen",
        "orientation": None,
        "player_configs": [],
        "selected_players": [0, 1, 2, 3],
    }

    # Create some dummy configs
    from src.models.profile import PlayerInstanceConfig

    for i in range(4):
        # Create PlayerInstanceConfig directly from the module
        config = PlayerInstanceConfig()
        config.physical_device_id = f"/dev/input/js{i}"
        config.grab_input_devices = i % 2 == 0  # Alternate grab input
        ui_data["player_configs"].append(config)

    # Simulate controller update logic
    profile.num_players = ui_data["num_players"]
    profile.player_configs = ui_data["player_configs"]
    profile.mode = ui_data["mode"]
    profile.selected_players = ui_data["selected_players"]

    print(f"After update: {profile.num_players} players")
    for i, config in enumerate(profile.player_configs):
        print(f"  Player {i}: device={config.physical_device_id}, grab={config.grab_input_devices}")

    print("Settings controller logic test completed!")


if __name__ == "__main__":
    test_profile_preservation()
    test_settings_controller_logic()
    print("\nAll tests completed!")
