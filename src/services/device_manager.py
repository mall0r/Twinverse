"""Discovery and management of input devices, audio sinks and display outputs."""

# flake8: noqa: E402

import json
import logging
import re
import subprocess
from typing import Dict, List, Optional, Tuple, TypedDict

import gi

gi.require_version("Gdk", "4.0")  # noqa: E402

import pydbus
from gi.repository import Gdk
from screeninfo import get_monitors

from src.core import LayoutCalculator
from src.core.tiling import build_tiling_plan
from src.models import Profile

logger = logging.getLogger(__name__)


class ScreenInfo(TypedDict):
    """Current pixel dimensions and connector identity of a display."""

    id: int
    name: str
    x: int
    y: int
    width: int
    height: int
    refresh_rate_mhz: int


class DeviceManager:
    """Discovers and manages system hardware devices."""

    def __init__(self):
        """Initialize the DeviceManager."""
        pass

    def _run_command(self, command: List[str]) -> str:
        """
        Execute a shell command and return its standard output.

        Args:
            command: The command and its arguments, as a list.

        Returns:
            The stripped stdout, or an empty string if the command is missing
            or exits non-zero; the failure is logged either way.
        """
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except FileNotFoundError:
            logger.error("Command not found: %s", command[0])
            return ""
        except subprocess.CalledProcessError as e:
            logger.error("Command failed: '%s' with error: %s", command, e.stderr.strip())
            return ""

    def _get_device_name_from_id(self, device_id_full: str) -> str:
        """
        Generate a human-readable name from a device's ID path.

        Args:
            device_id_full: A path under `/dev/input/by-id/`.

        Returns:
            The name with path prefixes and technical suffixes stripped.
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

        Returns:
            Keys "keyboard", "mouse" and "joystick", each holding devices as
            {"id": path, "name": human-readable name}.
        """
        detected_devices: Dict[str, List[Dict[str, str]]] = {
            "keyboard": [],
            "mouse": [],
            "joystick": [],
        }

        by_id_output = self._run_command(["ls", "-l", "/dev/input/by-id/"])

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
                logger.warning("Could not parse input device line '%s': %s", line, e)
                continue

        for dev_type in detected_devices:
            detected_devices[dev_type] = sorted(detected_devices[dev_type], key=lambda x: x["name"])
        return detected_devices

    def get_audio_devices(self) -> List[Dict[str, str]]:
        """
        Detect available audio output devices (sinks) using `pactl`.

        Returns:
            Sinks as {"id": PulseAudio name, "name": readable description}.
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
                logger.warning("Could not parse audio device line '%s': %s", line, e)
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
                logger.warning("Could not determine the primary monitor from Plasma: %s", e)
        return sorted(monitors, key=lambda monitor: not (monitor.is_primary or monitor.name == primary_name))

    def get_screen_info(self) -> List[ScreenInfo]:
        """Get information about connected screens/monitors."""
        # Match connectors rather than enumeration order: GDK and screeninfo
        # need not list monitors in the same order. GDK reports current mHz.
        display = Gdk.Display.get_default()
        refresh_rates = {}
        geometries = {}
        if display:
            for monitor in display.get_monitors():
                refresh_rates[monitor.get_connector()] = monitor.get_refresh_rate()
                geometries[monitor.get_connector()] = monitor.get_geometry()
        monitors: List[ScreenInfo] = []
        for i, monitor in enumerate(self.get_ordered_monitors()):
            width, height = monitor.width, monitor.height
            geometry = geometries.get(monitor.name)
            # Some screeninfo backends report the unrotated mode. GDK's
            # logical geometry already includes rotation; use only its aspect
            # orientation so desktop scaling does not change the pixel size.
            if geometry and geometry.width > 0 and geometry.height > 0 and geometry.width != geometry.height:
                if (width > height) != (geometry.width > geometry.height):
                    width, height = height, width
            monitors.append(
                {
                    "id": i,
                    "name": monitor.name or f"Monitor {i + 1}",
                    "x": monitor.x,
                    "y": monitor.y,
                    "width": width,
                    "height": height,
                    "refresh_rate_mhz": refresh_rates.get(monitor.name, 0),
                }
            )
        return monitors

    @staticmethod
    def _get_instance_monitor_index(profile: Profile, instance_num: int) -> int:
        """Use the same monitor assignment for dimensions and refresh rate."""
        slot = DeviceManager._get_instance_slot(profile, instance_num)
        if profile.is_splitscreen_mode and profile.splitscreen:
            return slot // 4
        return slot

    @staticmethod
    def _get_instance_slot(profile: Profile, instance_num: int) -> int:
        """
        Return the position of an instance inside the group being laid out.

        The position follows the configured display order, independently of
        the order in which instance processes or windows happen to start.
        """
        slots = DeviceManager._get_launch_slots(profile)
        return slots.get(instance_num, instance_num)

    @staticmethod
    def _get_launch_slots(profile: Profile) -> Dict[int, int]:
        """Map every selected instance to its configured display slot."""
        return {index: slot for slot, index in enumerate(profile.layout_indices())}

    @classmethod
    def _resolve_monitor_index(cls, profile: Profile, instance_num: int, num_monitors: int) -> int:
        """Fall back to the first monitor when there are more instances than monitors."""
        index = cls._get_instance_monitor_index(profile, instance_num)
        if num_monitors > 0 and index >= num_monitors:
            return 0
        return index

    def get_instance_placement(self, profile: Profile, instance_num: int):
        """Return (MonitorPlan, proportional rectangle), or None when unassigned.

        This helper is for explicit monitor layouts; legacy callers retain their
        existing slot calculation. Discovery is refreshed on every invocation.
        """
        plan = build_tiling_plan(profile.layout_indices(), self.get_screen_info(), profile.monitor_layouts)
        for monitor in plan.monitors:
            if instance_num in monitor.players:
                return monitor, monitor.template.rectangles[monitor.players.index(instance_num)]
        return None

    def get_instance_refresh_rate(self, profile: Profile, instance_num: int) -> Optional[int]:
        """Return the assigned monitor's current rate in Gamescope's integer Hz."""
        if profile.monitor_layouts:
            placement = self.get_instance_placement(profile, instance_num)
            rate = placement[0].display.get("refresh_rate_mhz", 0) if placement else 0
            return max(1, int(rate / 1000 + 0.5)) if rate > 0 else None
        monitors = sorted(self.get_screen_info(), key=lambda monitor: monitor["id"])
        index = self._resolve_monitor_index(profile, instance_num, len(monitors))
        if 0 <= index < len(monitors):
            rate = monitors[index].get("refresh_rate_mhz", 0)
            if rate > 0:
                return max(1, int(rate / 1000 + 0.5))
        return None

    def get_instance_dimensions(self, profile: Profile, instance_num: int) -> Tuple[Optional[int], Optional[int]]:
        """
        Calculate instance dimensions, accounting for splitscreen.

        The selected instances are laid out in groups of four, following the
        configured placement order, so a partial selection still fills the split.
        """
        if profile.monitor_layouts:
            placement = self.get_instance_placement(profile, instance_num)
            if placement is None:
                return None, None
            monitor, (_, _, width, height) = placement
            return int(monitor.display["width"] * width), int(monitor.display["height"] * height)
        monitors = self.get_screen_info()

        monitors_sorted = sorted(monitors, key=lambda x: x["id"])

        monitor_index = self._resolve_monitor_index(profile, instance_num, len(monitors_sorted))
        if not 0 <= monitor_index < len(monitors_sorted):
            return None, None
        monitor_to_use = monitors_sorted[monitor_index]

        if not profile.is_splitscreen_mode or not profile.splitscreen:
            return monitor_to_use["width"], monitor_to_use["height"]

        orientation = profile.splitscreen.orientation
        num_players = profile.effective_num_players()
        if num_players < 1:
            return monitor_to_use["width"], monitor_to_use["height"]

        slot = self._get_instance_slot(profile, instance_num)
        group_index = slot // 4
        instance_in_group = slot % 4
        num_players_in_group = min(4, num_players - group_index * 4)

        if num_players_in_group <= 0:
            return None, None
        if num_players_in_group == 1:
            return monitor_to_use["width"], monitor_to_use["height"]
        if instance_in_group < num_players_in_group:
            x, y, width, height = LayoutCalculator.calculate_position(
                monitor_to_use["width"],
                monitor_to_use["height"],
                num_players_in_group,
                instance_in_group,
                orientation,
            )
            return width, height

        return None, None
