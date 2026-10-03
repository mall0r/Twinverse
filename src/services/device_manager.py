"""
Device manager module for the Twinverse application.

This module provides functionality to discover and manage system hardware devices
such as input devices, audio devices, and display outputs.
"""

import json
import logging
import re
import subprocess
from typing import Dict, List, Optional, Tuple, Union

import gi
import pydbus
from gi.repository import Gdk
from screeninfo import get_monitors

from src.core import LayoutCalculator
from src.models import Profile

gi.require_version("Gdk", "4.0")


class DeviceManager:
    """
    Discovers and manages system hardware devices.

    This class provides methods to detect and list available input devices
    (keyboards, mice, joysticks), audio output devices (sinks), and display
    outputs (monitors) by interfacing with system command-line tools like
    `ls`, `pactl`, and `xrandr`.
    """

    def __init__(self):
        """Initialize the DeviceManager."""
        pass

    def _run_command(self, command: List[str]) -> str:
        """
        Execute a shell command and return its standard output.

        Args:
            command (List[str]): The command to execute as a list of arguments.

        Returns:
            str: The stripped stdout from the command, or an empty string
                 if an error occurs.
        """
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except FileNotFoundError:
            logging.error(f"Command not found: {command[0]}")
            return ""
        except subprocess.CalledProcessError as e:
            logging.error(f"Command failed: '{command}' with error: {e.stderr.strip()}")
            return ""

    def _get_device_name_from_id(self, device_id_full: str) -> str:
        """
        Generate a human-readable name from a device's ID path.

        It cleans up the raw device ID string by removing path prefixes and
        technical suffixes, making it more suitable for display in a UI.

        Args:
            device_id_full (str): The full device path from `/dev/input/by-id/`.

        Returns:
            str: A cleaned, human-readable device name.
        """
        name_part = device_id_full.replace("/dev/input/by-id/", "")
        name_part = re.sub(r"-event-(kbd|mouse|joystick)", "", name_part)
        name_part = re.sub(r"-if\d+", "", name_part)
        name_part = name_part.replace("usb-", "").replace("_", " ")
        name_part = " ".join([word.capitalize() for word in name_part.split(" ")]).strip()
        return name_part

    def get_input_devices(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Detect and categorize available input devices.

        Parse the output of `ls -l /dev/input/by-id/` to find keyboards,
        mice, and joysticks.

        Returns:
            Dict[str, List[Dict[str, str]]]: A dictionary where keys are
            "keyboard", "mouse", and "joystick". Each key holds a list of
            device dictionaries, with each dictionary containing the
            device's 'id' (path) and 'name' (human-readable).
        """
        detected_devices: Dict[str, List[Dict[str, str]]] = {
            "keyboard": [],
            "mouse": [],
            "joystick": [],
        }

        by_id_output = self._run_command(["ls", "-l", "/dev/input/by-id/"])

        # A more specific regex to find symlinks to event devices.
        device_pattern = re.compile(r"\s([^\s]+)\s+->\s+\.\./event\d+")

        for line in by_id_output.splitlines():
            try:
                match = device_pattern.search(line)
                if match:
                    device_name_id_raw = match.group(1)
                    full_path = f"/dev/input/by-id/{device_name_id_raw}"
                    human_name = self._get_device_name_from_id(full_path)
                    device = {"id": full_path, "name": human_name}

                    if "event-joystick" in device_name_id_raw:
                        detected_devices["joystick"].append(device)
                    elif "event-mouse" in device_name_id_raw:
                        detected_devices["mouse"].append(device)
                    elif "event-kbd" in device_name_id_raw:
                        detected_devices["keyboard"].append(device)
            except (IndexError, AttributeError) as e:
                logging.warning(f"Could not parse input device line: '{line}'. Error: {e}")
                continue

        for dev_type in detected_devices:
            detected_devices[dev_type] = sorted(detected_devices[dev_type], key=lambda x: x["name"])
        return detected_devices

    def get_audio_devices(self) -> List[Dict[str, str]]:
        """
        Detect available audio output devices (sinks) using `pactl`.

        Returns:
            List[Dict[str, str]]: A list of dictionaries, where each
            dictionary represents an audio sink and contains its 'id'
            (PulseAudio name) and 'name' (readable description).
        """
        audio_sinks = []

        # Comando pactl com variável de ambiente para garantir saída em inglês
        pactl_output = self._run_command(["sh", "-c", "LANG=C pactl list sinks"])

        desc, name = None, None

        for line in pactl_output.splitlines():
            try:
                if line.startswith("Sink #"):
                    if name:
                        audio_sinks.append({"id": name, "name": desc or name})
                    desc, name = None, None
                elif "Description:" in line:
                    desc = line.split(":", 1)[1].strip()
                elif "Name:" in line:
                    name = line.split(":", 1)[1].strip()
            except (IndexError, AttributeError) as e:
                logging.warning(f"Could not parse audio device line: '{line}'. Error: {e}")
                continue

        if name:
            audio_sinks.append({"id": name, "name": desc or name})

        return sorted(audio_sinks, key=lambda x: x["name"])

    @staticmethod
    def get_ordered_monitors():
        """Put the primary monitor first, preserving the order of other outputs."""
        monitors = get_monitors()
        primary_name = None
        if monitors and not any(monitor.is_primary for monitor in monitors):
            # Flatpak's screeninfo backend may omit primary status. Plasma's
            # screen 0 is the primary; query it through the existing D-Bus access.
            try:
                plasma = pydbus.SessionBus().get("org.kde.plasmashell", "/PlasmaShell")
                names = json.dumps([monitor.name for monitor in monitors])
                primary_name = plasma.evaluateScript(
                    f"print({names}.find(function (name) {{ return screenForConnector(name) === 0; }}) || '');"
                ).strip()
            except Exception as e:
                logging.warning(f"Could not determine the primary monitor from Plasma: {e}")
        return sorted(monitors, key=lambda monitor: not (monitor.is_primary or monitor.name == primary_name))

    def get_screen_info(self) -> List[Dict[str, Union[int, bool]]]:
        """Get information about connected screens/monitors."""
        # Match connectors rather than enumeration order: GDK and screeninfo
        # need not list monitors in the same order. GDK reports current mHz.
        display = Gdk.Display.get_default()
        refresh_rates = {}
        if display:
            for monitor in display.get_monitors():
                refresh_rates[monitor.get_connector()] = monitor.get_refresh_rate()
        monitors = []
        for i, monitor in enumerate(self.get_ordered_monitors()):
            monitors.append(
                {
                    "id": i,
                    "x": monitor.x,
                    "y": monitor.y,
                    "width": monitor.width,
                    "height": monitor.height,
                    "refresh_rate_mhz": refresh_rates.get(monitor.name, 0),
                }
            )
        return monitors

    @staticmethod
    def _get_instance_monitor_index(profile: Profile, instance_num: int) -> int:
        """Use the same monitor assignment for dimensions and refresh rate."""
        if profile.is_splitscreen_mode and profile.splitscreen:
            return instance_num // 4 if profile.effective_num_players() > 0 else 0
        return instance_num

    def get_instance_refresh_rate(self, profile: Profile, instance_num: int) -> Optional[int]:
        """Return the assigned monitor's current rate in Gamescope's integer Hz."""
        monitors = sorted(self.get_screen_info(), key=lambda monitor: monitor["id"])
        index = self._get_instance_monitor_index(profile, instance_num)
        if 0 <= index < len(monitors):
            rate = monitors[index].get("refresh_rate_mhz", 0)
            if rate > 0:
                return max(1, int(rate / 1000 + 0.5))
        return None

    def get_instance_dimensions(self, profile: Profile, instance_num: int) -> Tuple[Optional[int], Optional[int]]:
        """
        Calculate instance dimensions, accounting for splitscreen.

        For groups of up to 4 instances, the logic is repeated for each group.
        """
        monitors = self.get_screen_info()

        monitors_sorted = sorted(monitors, key=lambda x: x["id"])

        monitor_index = self._get_instance_monitor_index(profile, instance_num)
        if not 0 <= monitor_index < len(monitors_sorted):
            return None, None
        monitor_to_use = monitors_sorted[monitor_index]

        if not profile.is_splitscreen_mode or not profile.splitscreen:
            # Fullscreen mode
            return monitor_to_use["width"], monitor_to_use["height"]
        else:
            # Splitscreen mode
            orientation = profile.splitscreen.orientation
            num_players = profile.effective_num_players()

            if num_players < 1:
                return monitor_to_use["width"], monitor_to_use["height"]
            else:
                group_index = instance_num // 4

                # Applies splitscreen logic within the group.
                instance_in_group = instance_num % 4
                num_players_in_group = min(4, num_players - group_index * 4)

                if monitor_to_use and num_players_in_group > 0:
                    # Special case: if there's only 1 player in the group, return full monitor size
                    if num_players_in_group == 1:
                        return monitor_to_use["width"], monitor_to_use["height"]

                    if instance_in_group < num_players_in_group:
                        # Use the new layout calculator
                        x, y, width, height = LayoutCalculator.calculate_position(
                            monitor_to_use["width"],
                            monitor_to_use["height"],
                            num_players_in_group,
                            instance_in_group,
                            orientation,
                        )
                        return width, height
                    else:
                        # If instance_in_group is greater than or equal to num_players_in_group,
                        # return None, None as in the original logic
                        return None, None

        if monitor_to_use:
            return monitor_to_use["width"], monitor_to_use["height"]

        return None, None
