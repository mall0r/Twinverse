"""Builds the launch commands for Steam instances, with gamescope and bwrap sandboxing."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from src.core.exceptions import TwinverseError
from src.core.utils import Utils
from src.models import Profile
from src.services.device_manager import DeviceManager
from src.services.kwin_layout import INSTANCE_ENV
from src.services.network import steam_private_ip_override
from src.services.virtual_uinput import (
    ENV_HIDRAW_FILTER,
    ENV_PHYSICAL_BRIDGE,
    ENV_SOCKET_DIR,
    ENV_VIRTUAL_UINPUT,
    ENV_VIRTUAL_UINPUT_PRELOAD,
    build_input_bridge_command,
    find_hidraw_devices_to_mask,
    stage_virtual_uinput,
)
from src.services.webhelper_sync import build_webhelper_mounts

logger = logging.getLogger(__name__)


class CommandBuilder:
    """Builds the launch commands for Steam instances."""

    MANGOAPP_CONFIG = Path(".config/twinverse/mangoapp.conf")
    GAMESCOPE_TOUCH_MODE_ENV = "gamescope_touch_click_mode"
    # Steam can change the mode after startup (Gamescope #2582). Gamescope's
    # ConVar environment parser splits on "=", so avoid Lua's equality operator.
    GAMESCOPE_POINTER_COMPATIBILITY = (
        '(function(m) gamescope.hook("OnPostPaint", function() '
        'if m.value > 3 and m.value < 5 then m:call("1") end end); '
        "return m.value end)(gamescope.convars.touch_click_mode)"
    )

    # Gamescope creates this path at startup, so expand it in its child, not
    # while building the command. Proton's runtime otherwise hides the file
    # under /run/user, and the Vulkan layer silently disables FIFO enforcement.
    # Userspace /dev/uinput LD_PRELOAD is also activated here so Gamescope
    # itself is never preloaded while Steam and Proton inherit it.
    GAMESCOPE_RUNTIME_SETUP = r"""
if [ -n "${GAMESCOPE_LIMITER_FILE:-}" ]; then
    export PRESSURE_VESSEL_FILESYSTEMS_RO=\
"${PRESSURE_VESSEL_FILESYSTEMS_RO:+${PRESSURE_VESSEL_FILESYSTEMS_RO}:}${GAMESCOPE_LIMITER_FILE}"
fi
if [ -n "${TWINVERSE_VIRTUAL_UINPUT_PRELOAD:-}" ]; then
    export TWINVERSE_VIRTUAL_UINPUT=1
    export LD_PRELOAD="${TWINVERSE_VIRTUAL_UINPUT_PRELOAD}${LD_PRELOAD:+:${LD_PRELOAD}}"
    unset TWINVERSE_VIRTUAL_UINPUT_PRELOAD
fi
exec "$@"
"""

    def prepare_overlay_environment(self) -> Dict[str, Optional[str]]:
        """Give MangoApp a config that Steam can update through the isolated home."""
        if not (self.profile.use_gamescope and self.profile.use_steamdeck_tag):
            return {}

        config_path = self.home_path / self.MANGOAPP_CONFIG
        config_path.parent.mkdir(parents=True, exist_ok=True)
        # Start hidden until Steam applies the user's performance overlay level.
        # The file is kept once it exists, so the level the user picked in the
        # Steam performance menu survives the next launch.
        if not config_path.exists():
            config_path.write_text("no_display\n", encoding="utf-8")
        # An empty inline config skips file loading; read_cfg reapplies presets
        # in MangoHud 0.8.4, duplicating HUD elements. None means unset it.
        return {"MANGOHUD_CONFIGFILE": str(config_path), "MANGOHUD_CONFIG": None}

    def __init__(
        self,
        profile: Profile,
        device_info: Dict,
        device_manager: DeviceManager,
        instance_num: int,
        home_path: Path,
        virtual_joystick_path: Optional[str],
    ):
        """Initialize the CommandBuilder."""
        self.profile = profile
        self.device_info = device_info
        self.device_manager = device_manager
        self.instance_num = instance_num
        self.home_path = home_path
        self.virtual_joystick_path = virtual_joystick_path
        self.input_bridge_command: Optional[List[str]] = None

    def build_command(self, application_command: Optional[List[str]] = None) -> List[str]:
        """
        Build the final command array in the correct order.

        [bwrap] -> [gamescope] -> [steam]  (when gamescope is enabled)
        [bwrap] -> [steam]                  (when gamescope is disabled)
        """
        steam_cmd = application_command if application_command is not None else self._build_base_steam_command()

        bwrap_cmd = self._build_bwrap_command(self.instance_num)

        final_cmd = steam_cmd

        if self.profile.use_gamescope:
            self._prepare_pipewire_config()
            should_add_grab_flags = self.device_info.get("should_add_grab_flags", False)
            gamescope_cmd = self._build_gamescope_command(should_add_grab_flags)

            # Pass the instance's live limiter file through Steam to Proton.
            final_cmd = ["sh", "-c", self.GAMESCOPE_RUNTIME_SETUP, "twinverse-gamescope"] + final_cmd

            final_cmd = gamescope_cmd + ["--"] + final_cmd
            logger.info("Instance %s: launching with Gamescope", self.instance_num + 1)
        else:
            logger.info("Instance %s: launching without Gamescope (bwrap only)", self.instance_num + 1)

        return bwrap_cmd + ["--"] + final_cmd

    def _prepare_pipewire_config(self) -> None:
        """Match Steam's video capture to this instance's Gamescope source."""
        config_path = self.home_path / ".config/pipewire/client.conf.d/90-twinverse-gamescope.conf"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        node_name = f"twinverse-gamescope-{self.instance_num}"
        # Both clients read this drop-in through the existing isolated home.
        # Restrict the target rule to Gamescope capture, leaving audio and
        # portal-selected desktop capture unchanged.
        config_path.write_text(
            f"""# Generated by Twinverse for this instance's Remote Play capture.
stream.rules = [
    {{
        matches = [ {{ media.name = "gamescope" media.class = "Video/Source" }} ]
        actions = {{ update-props = {{ node.name = "{node_name}" }} }}
    }}
    {{
        matches = [ {{ media.name = "steam-pipewire-stream" target.object = "gamescope" }} ]
        actions = {{ update-props = {{ target.object = "{node_name}" }} }}
    }}
]
""",
            encoding="utf-8",
        )

    def _build_gamescope_command(self, should_add_grab_flags: bool) -> List[str]:
        """Build the Gamescope command."""
        width, height = self.device_manager.get_instance_dimensions(self.profile, self.instance_num)
        if not width or not height:
            # Returning an empty command would turn the final line into
            # "bwrap ... -- -- ...", and bwrap would fail on a program named
            # "--" instead of reporting the real problem.
            raise TwinverseError(
                f"Instance {self.instance_num}: could not resolve the display size for this instance. "
                "Check that a monitor is connected and that the instance is part of the current layout."
            )

        # fmt: off
        cmd = [
            "gamescope",
            "-e",
            "-W", str(width),
            "-H", str(height),
            "-w", str(width),
            "-h", str(height),
            "--adaptive-sync",
        ]
        # fmt: on

        refresh_rate = self.device_manager.get_instance_refresh_rate(self.profile, self.instance_num)
        if refresh_rate:
            cmd.extend(["-r", str(refresh_rate), "-o", str(refresh_rate)])
        else:
            logger.warning("Instance %s: could not detect the monitor refresh rate", self.instance_num + 1)

        if self.profile.use_steamdeck_tag:
            cmd.append("--mangoapp")

        if self.profile.monitor_layouts:
            placement = self.device_manager.get_instance_placement(self.profile, self.instance_num)
            cmd.append("-f" if placement and placement[0].template.id == "fullscreen" else "-b")
        elif not self.profile.is_splitscreen_mode:
            cmd.append("-f")
        else:
            cmd.append("-b")

        if should_add_grab_flags:
            logger.info("Instance %s: using dedicated mouse and grabbing input", self.instance_num + 1)
            cmd.append("--force-grab-cursor")

        return cmd

    def _build_base_steam_command(self) -> List[str]:
        """Build the base steam command."""
        cmd = ["steam"]

        if self.profile.use_gamescope:
            if self.profile.use_steamdeck_tag:
                cmd.append("-steamdeck")
            logger.info("Instance %s: using Steam command with Gamescope flags", self.instance_num + 1)
            cmd.extend(["-gamepadui", "-steamos3"])
        else:
            logger.info("Instance %s: using plain Steam command", self.instance_num + 1)

        # Give each instance a distinct synthetic private IP for Steam's CM
        # logon session ID so logging into the same account on the shared host
        # network never kicks host Steam with ``Session Replaced``.
        private_ip = steam_private_ip_override(self.instance_num)
        cmd.extend(["-private_ip_override", private_ip])
        logger.debug("Instance %s: passing -private_ip_override %s to Steam", self.instance_num + 1, private_ip)

        return cmd

    @staticmethod
    def _host_steam_path(visible_steam_path: Path) -> Path:
        """
        Return the path the host uses for the shared Steam folders.

        Inside a Flatpak the shared folders are visible under the sandboxed
        home, but the command runs on the host, which resolves them from the
        real home directory.
        """
        if not Utils.is_flatpak():
            return visible_steam_path
        host_home = Utils.get_host_home()
        if host_home is None:
            return visible_steam_path
        return host_home / ".local/share/Steam"

    def _build_bwrap_command(self, instance_idx: int) -> List[str]:
        """
        Build the bwrap command for sandboxing.

        This strategy uses the real user's home directory but mounts instance-specific
        Steam directories over the real ones to achieve isolation.
        """
        self.input_bridge_command = None
        orig_home = Path.home()
        orig_local = orig_home / ".local"

        # Stage native virtual uinput + hotplug bridge before device isolation so
        # we know whether the physical controller will be bridged dynamically.
        virtual_uinput = stage_virtual_uinput(self.home_path, orig_home)

        # fmt: off
        cmd = [
            "bwrap",
            "--dev-bind", "/", "/",
            "--dev-bind", "/dev", "/dev",
            "--tmpfs", "/dev/shm",
            "--proc", "/proc",
            "--die-with-parent",
            "--tmpfs", "/tmp",
        ]
        # fmt: on

        if self.profile.use_gamescope:
            # Gamescope and MangoApp must share a queue private to this instance.
            cmd.append("--unshare-ipc")
            # Let Xwayland create .X11-unix in our private /tmp. The host's
            # root-owned directory maps to UID 65534 here and wlroots rejects it.
        else:
            cmd.extend(["--bind", "/tmp/.X11-unix", "/tmp/.X11-unix"])

        # --- Device Isolation ---

        cmd.extend(["--tmpfs", "/dev/input"])

        physical_joystick_path = self.device_info.get("joystick_path_str_for_instance")
        physical_device_id = self.device_info.get("joystick_device_id_for_instance")
        bridge_cmd = build_input_bridge_command(
            virtual_uinput,
            device_id=physical_device_id,
            resolved_event=physical_joystick_path,
        )

        if bridge_cmd is not None:
            # The host-side hotplug bridge exposes this physical controller as
            # virtual /dev/input/event3000 and dynamically manages /dev/hidraw*
            # visibility via tw_hidraw.allow across unplug/reconnect cycles.
            self.input_bridge_command = bridge_cmd
            logger.info(
                "Instance %s: hotplug controller bridge enabled for '%s'",
                self.instance_num + 1,
                physical_device_id or physical_joystick_path,
            )
        else:
            joystick_path = physical_joystick_path
            if not joystick_path and self.virtual_joystick_path:
                logger.info(
                    "Instance %s: assigning virtual joystick '%s'",
                    self.instance_num + 1,
                    self.virtual_joystick_path,
                )
                joystick_path = self.virtual_joystick_path

            if joystick_path:
                logger.info("Instance %s: exposing device '%s' to sandbox", self.instance_num + 1, joystick_path)
                cmd.extend(["--dev-bind", joystick_path, joystick_path])

            for hidraw_path in find_hidraw_devices_to_mask(joystick_path):
                cmd.extend(["--ro-bind", "/dev/null", hidraw_path])

        if Path("/dev/uinput").exists():
            # Keep /dev/uinput read-only so sandboxed apps never leak virtual
            # input devices into the host kernel. Steam Input creates isolated
            # per-sandbox virtual controllers via Twinverse's userspace uinput.
            cmd.extend(["--ro-bind", "/dev/uinput", "/dev/uinput"])
        if Path("/dev/input/mice").exists():
            cmd.extend(["--dev-bind", "/dev/input/mice", "/dev/input/mice"])

        # --- Home Directory Isolation ---
        # fmt: off

        cmd.extend(["--bind", str(self.home_path), str(orig_home)])

        # fmt: on
        # The instance home shadows the real one, so the shared Steam folders
        # are mounted back into it. The listing uses the path this process can
        # read, the source of the bind the path the host resolves, which
        # differs inside a Flatpak, and the destination lives in the instance.
        sandbox_steam_path = orig_local / "share/Steam"
        host_steam_path = self._host_steam_path(sandbox_steam_path)

        visible_common = sandbox_steam_path / "steamapps/common"
        host_common = host_steam_path / "steamapps/common"
        if visible_common.exists():
            for folder in visible_common.iterdir():
                if folder.is_dir():
                    cmd.extend(["--bind", str(host_common / folder.name), str(visible_common / folder.name)])

        visible_compat = sandbox_steam_path / "compatibilitytools.d"
        host_compat = host_steam_path / "compatibilitytools.d"
        if visible_compat.exists():
            ignore = {"LegacyRuntime"}
            for folder in visible_compat.iterdir():
                if folder.is_dir() and folder.name not in ignore:
                    cmd.extend(["--bind", str(host_compat / folder.name), str(visible_compat / folder.name)])

        # The UI must not open placeholder controller memory before Steam does.
        cmd.extend(
            build_webhelper_mounts(
                self.home_path,
                self.instance_num,
                fix_overlay_focus=self.profile.use_gamescope and self.profile.is_splitscreen_mode,
            )
        )

        extra_env: Dict = {}
        try:
            extra_env = (
                self.profile.get_env_for_instance(instance_idx) if hasattr(self.profile, "get_env_for_instance") else {}
            ) or {}
            if self.profile.use_gamescope and self.profile.enable_gamescope_pointer_compatibility:
                extra_env.setdefault(self.GAMESCOPE_TOUCH_MODE_ENV, self.GAMESCOPE_POINTER_COMPATIBILITY)
            for k, v in extra_env.items():
                if v is None:
                    v = ""
                cmd.extend(["--setenv", str(k), str(v)])
            if extra_env:
                logger.info("Instance %s: added %s --setenv entries to bwrap", self.instance_num + 1, len(extra_env))
        except Exception:
            logger.exception("Instance %s: failed to add --setenv entries", self.instance_num + 1)

        if virtual_uinput is not None:
            cmd.extend(["--setenv", ENV_SOCKET_DIR, str(virtual_uinput.socket_dir)])
            if self.input_bridge_command is not None:
                cmd.extend(["--setenv", ENV_PHYSICAL_BRIDGE, "1"])
                cmd.extend(["--setenv", ENV_HIDRAW_FILTER, "1"])
            if self.profile.use_gamescope:
                # GAMESCOPE_RUNTIME_SETUP moves this into LD_PRELOAD after
                # gamescope spawns its child so gamescope itself is untouched.
                cmd.extend(["--setenv", ENV_VIRTUAL_UINPUT_PRELOAD, virtual_uinput.preload_value])
            else:
                cmd.extend(["--setenv", ENV_VIRTUAL_UINPUT, "1"])
                existing_preload = extra_env.get("LD_PRELOAD") or os.environ.get("LD_PRELOAD")
                preload = (
                    f"{virtual_uinput.preload_value}:{existing_preload}"
                    if existing_preload
                    else virtual_uinput.preload_value
                )
                cmd.extend(["--setenv", "LD_PRELOAD", preload])
            logger.info(
                "Instance %s: enabled userspace /dev/uinput for Steam Input (socket dir: %s)",
                self.instance_num + 1,
                virtual_uinput.socket_dir,
            )

        if self.profile.use_gamescope and self.profile.use_steamdeck_tag:
            # Gamescope, MangoApp and Steam share the sandbox home path.
            # Override the host path used to prepare the config before launch.
            cmd.extend(["--setenv", "MANGOHUD_CONFIGFILE", str(orig_home / self.MANGOAPP_CONFIG)])
            cmd.extend(["--unsetenv", "MANGOHUD_CONFIG"])
        if self.profile.use_gamescope:
            # Set this after user environment overrides. Gamescope keeps the
            # marker even when it recreates its host window or changes title.
            cmd.extend(["--setenv", INSTANCE_ENV, str(instance_idx)])
        return cmd
