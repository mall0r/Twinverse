"""Launch, termination and configuration of Steam instances in isolated environments."""

import copy
import os
import shlex
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Optional

from src.core import Config, Logger, Utils
from src.core.exceptions import DependencyError, TwinverseError, VirtualDeviceError
from src.models import PlayerInstanceConfig, Profile

from .kde_manager import KdeManager
from .network import network_command
from .steam_input import SteamInputDisabler


class InstanceService:
    """Tracks the process, PGID and Popen of every managed instance."""

    def __init__(self, logger: Logger, kde_manager: Optional[KdeManager] = None):
        """Initialize the instance service."""
        from .device_manager import DeviceManager
        from .virtual_device import VirtualDeviceService

        self.logger = logger
        self.steam_input = SteamInputDisabler(logger)
        self.virtual_device = VirtualDeviceService(logger)
        self.kde_manager = kde_manager
        self.device_manager = DeviceManager()
        self._virtual_joystick_path: Optional[str] = None
        self._virtual_joystick_checked: bool = False
        self.pids: dict[int, int] = {}
        self.pgids: dict[int, int] = {}
        self.processes: dict[int, subprocess.Popen] = {}
        self.termination_in_progress = False

    def _prepare_instance_launch(
        self, profile: Profile, instance_num: int, application_command: Optional[list[str]] = None
    ) -> tuple[list[str], dict]:
        """Prepare and build the command for launching a single Steam instance."""
        if application_command is None:
            process = self.processes.get(instance_num)
            if process is not None and process.poll() is None:
                raise TwinverseError(f"Instance {instance_num + 1} is already running.")

        home_path = Config.get_steam_home_path(instance_num)
        home_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Instance {instance_num}: Using isolated home path '{home_path}'")

        self._prepare_home(home_path)
        if application_command is None:
            self._sync_app_manifests(home_path)
            # Steam rewrites localconfig.vdf when it exits, so the change has to
            # land before the client starts reading it.
            self.steam_input.disable_once(instance_num, home_path)

        device_info = self._validate_input_devices(profile, instance_num, instance_num)
        instance_env = self._prepare_environment(profile, device_info, instance_num)

        from .cmd_builder import CommandBuilder

        cmd_builder = CommandBuilder(
            self.logger,
            profile,
            device_info,
            self.device_manager,
            instance_num,
            home_path,
            self._virtual_joystick_path,
        )
        instance_env.update(cmd_builder.prepare_overlay_environment())
        return cmd_builder.build_command(application_command), instance_env

    def _launch_single_instance(self, profile: Profile, instance_num: int) -> None:
        """Launch a single steam instance."""
        self.logger.info(f"Preparing instance {instance_num}...")

        base_command, instance_env = self._prepare_instance_launch(profile, instance_num)

        log_file = Config.LOG_DIR / f"steam_instance_{instance_num}.log"
        self.logger.info(f"Launching instance {instance_num} (Log: {log_file})")
        self.logger.debug(f"Instance {instance_num}: Environment: {dict(instance_env)}")

        try:
            if Utils.is_flatpak():
                self.logger.info(f"Instance {instance_num}: Launching in Flatpak environment")
                process, pgid = self._launch_in_flatpak(instance_num, base_command, instance_env)
            else:
                self.logger.info(f"Instance {instance_num}: Launching natively")
                process, pgid = self._launch_natively(instance_num, base_command, instance_env)

            self.pids[instance_num] = process.pid
            self.pgids[instance_num] = pgid
            self.processes[instance_num] = process

            self.logger.info(f"Instance {instance_num}: Successfully launched with PID {process.pid}")

        except TwinverseError:
            self.logger.error(f"Instance {instance_num}: TwinverseError during launch")
            raise
        except Exception as e:
            self.logger.error(f"Instance {instance_num}: Unexpected error during launch: {str(e)}")
            self.logger.exception(f"Instance {instance_num}: Exception details:")
            raise TwinverseError(f"Failed to launch instance {instance_num}: {str(e)}")

    @staticmethod
    def _drain_stream(stream, log_file: Path) -> None:
        """
        Consume a pipe in the background, so the child never blocks on it.

        A pipe holds about 64 KiB, and the child blocks on write once it is
        full. Reading it here keeps the output in the instance log and leaves
        the instance running.
        """
        if stream is None:
            return

        def _pump() -> None:
            try:
                with open(log_file, "ab") as sink:
                    for chunk in iter(lambda: stream.read(4096), b""):
                        sink.write(chunk)
            except (OSError, TypeError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except (OSError, TypeError, ValueError):
                    pass

        threading.Thread(target=_pump, daemon=True).start()

    @staticmethod
    def _read_log_tail(log_file: Path, limit: int = 2000) -> str:
        """Return the end of an instance log, for the error message."""
        try:
            with open(log_file, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - limit))
                return handle.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""

    def _launch_in_flatpak(
        self, instance_num: int, base_command: list[str], instance_env: dict, log_file: Optional[Path] = None
    ) -> tuple[subprocess.Popen, int]:
        """Launch a Steam instance within a Flatpak environment."""
        log_file = log_file or Config.LOG_DIR / f"steam_instance_{instance_num}.log"
        env_prefix_parts = [
            f"unset {shlex.quote(key)}" if value is None else f"export {shlex.quote(key)}={shlex.quote(value)}"
            for key, value in instance_env.items()
        ]
        env_prefix = "; ".join(env_prefix_parts) + "; " if env_prefix_parts else ""
        escaped_command = shlex.join(base_command)
        network_launch = shlex.join(network_command(base_command))
        shell_command = (
            f"{env_prefix}set -m; echo $$; "
            f"if command -v pasta >/dev/null 2>&1; then exec {network_launch}; "
            f"else exec {escaped_command}; fi"
        )

        self.logger.info(f"Instance {instance_num}: Launching on host via shell: {shell_command}")

        flatpak_env = os.environ.copy()
        flatpak_env.pop("PYTHONHOME", None)
        flatpak_env.pop("PYTHONPATH", None)

        try:
            process = Utils.flatpak_spawn_host(
                ["bash", "-c", shell_command],
                async_=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=flatpak_env,
                cwd=Path.home(),
            )
        except FileNotFoundError as e:
            self.logger.error(f"Instance {instance_num}: flatpak-spawn-host command not found: {e}")
            raise DependencyError(f"flatpak-spawn-host command not found: {e}")
        except PermissionError as e:
            self.logger.error(f"Instance {instance_num}: Permission denied when spawning host process: {e}")
            raise TwinverseError(f"Permission denied when launching instance {instance_num}: {e}")
        except Exception as e:
            self.logger.error(f"Instance {instance_num}: Unexpected error when spawning host process: {e}")
            raise TwinverseError(f"Unexpected error when launching instance {instance_num}: {e}")

        import time

        time.sleep(0.1)

        if process.poll() is not None:
            stdout_data, stderr_data = process.communicate()
            stdout_str = stdout_data.decode() if stdout_data else ""
            stderr_str = stderr_data.decode() if stderr_data else ""
            error_message = (
                f"STDOUT: {stdout_str}\nSTDERR: {stderr_str}" if (stdout_str or stderr_str) else "Unknown error"
            )
            self.logger.error(f"Instance {instance_num}: Process failed to start:\n{error_message}")
            raise DependencyError(f"Command failed to start: {base_command[0]} - {error_message}")

        pgid_str = process.stdout.readline().decode().strip() if process.stdout else ""
        if pgid_str.isdigit():
            pgid = int(pgid_str)
            # From here on the pipes are only drained, so the instance keeps
            # running while its output lands in the log.
            self._drain_stream(process.stdout, log_file)
            self._drain_stream(process.stderr, log_file)
            self.logger.info(
                f"Instance {instance_num} started on host with PID {process.pid} " f"and captured host PGID: {pgid}"
            )
            return process, pgid

        self.logger.error(f"Instance {instance_num}: Failed to capture host PGID. Read: '{pgid_str}'")
        process.terminate()

        stdout_data, stderr_data = process.communicate(timeout=1) if process.stdout else (None, None)
        stdout_str = stdout_data.decode() if stdout_data else ""
        stderr_str = stderr_data.decode() if stderr_data else ""
        error_message = (
            f"STDOUT: {stdout_str}\nSTDERR: {stderr_str}"
            if (stdout_str or stderr_str)
            else "Failed to capture host PGID"
        )

        raise TwinverseError(f"Failed to get host process group ID for instance {instance_num}: {error_message}")

    def _launch_natively(
        self, instance_num: int, base_command: list[str], instance_env: dict, log_file: Optional[Path] = None
    ) -> tuple[subprocess.Popen, int]:
        """Launch a Steam instance natively."""
        log_file = log_file or Config.LOG_DIR / f"steam_instance_{instance_num}.log"
        native_env = os.environ.copy()
        native_env.pop("PYTHONHOME", None)
        native_env.pop("PYTHONPATH", None)
        for key, value in instance_env.items():
            if value is None:
                native_env.pop(key, None)
            else:
                native_env[key] = value

        self.logger.info(f"Instance {instance_num}: Full command: {shlex.join(base_command)}")

        self.logger.debug(f"Instance {instance_num}: Environment variables: {list(instance_env.keys())}")

        if not shutil.which(base_command[0]):
            error_msg = f"Command '{base_command[0]}' not found in PATH"
            self.logger.error(f"Instance {instance_num}: {error_msg}")
            raise DependencyError(error_msg)

        if shutil.which("pasta"):
            base_command = network_command(base_command)

        try:
            # The output goes straight to the instance log, so a chatty Steam
            # or Proton session can never fill a pipe and block the instance.
            output = open(log_file, "ab")
        except OSError as e:
            self.logger.error(f"Instance {instance_num}: Could not open the instance log: {e}")
            raise TwinverseError(f"Could not open the instance log for instance {instance_num}: {e}")

        try:
            process = subprocess.Popen(
                base_command,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=native_env,
                cwd=Path.home(),
                preexec_fn=os.setpgrp,
            )
        except FileNotFoundError as e:
            self.logger.error(f"Instance {instance_num}: Command not found: {e}")
            raise DependencyError(f"Command not found: {e}")
        except PermissionError as e:
            self.logger.error(f"Instance {instance_num}: Permission denied: {e}")
            raise TwinverseError(f"Permission denied when launching instance {instance_num}: {e}")
        except OSError as e:
            self.logger.error(f"Instance {instance_num}: OS error when launching: {e}")
            raise TwinverseError(f"OS error when launching instance {instance_num}: {e}")
        finally:
            # The child keeps its own copy of the descriptor.
            output.close()

        import time

        time.sleep(0.1)

        if process.poll() is not None:
            error_message = self._read_log_tail(log_file) or "Unknown error"
            self.logger.error(f"Instance {instance_num}: Process failed to start:\n{error_message}")
            raise DependencyError(f"Command failed to start: {base_command[0]} - {error_message}")

        pgid = process.pid
        self.logger.info(f"Instance {instance_num} started with PID: {process.pid} and PGID: {pgid}")
        return process, pgid

    def launch_instance(
        self,
        profile: Profile,
        instance_num: int,
        use_gamescope_override: Optional[bool] = None,
    ) -> None:
        """Launch a single Steam instance."""
        active_profile = self._prepare_launch_profile(profile, use_gamescope_override)
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._launch_single_instance(active_profile, instance_num)

    def _prepare_launch_profile(self, profile: Profile, use_gamescope_override: Optional[bool]) -> Profile:
        """Prepare devices and profile overrides shared by Steam and terminal launches."""
        if not self._virtual_joystick_checked:
            self._virtual_joystick_checked = True
            needs_virtual_joystick = False
            # Only the instances that take part in the launch need a device, so
            # the check follows the launch order instead of the instance index.
            for index in profile.launch_indices():
                player_config = (
                    profile.player_configs[index]
                    if profile.player_configs and index < len(profile.player_configs)
                    else PlayerInstanceConfig()
                )
                if not player_config.physical_device_id:
                    needs_virtual_joystick = True
                    break

            if needs_virtual_joystick:
                self.logger.info("One or more instances lack a physical joystick. Creating a virtual one.")
                try:
                    self._virtual_joystick_path = self.virtual_device.create_virtual_joystick()
                except VirtualDeviceError as e:
                    self.logger.error(f"Halting launch due to virtual joystick creation failure: {str(e)}")
                    raise

        active_profile = profile
        if use_gamescope_override is not None:
            active_profile = copy.deepcopy(profile)
            active_profile.use_gamescope = use_gamescope_override

            if use_gamescope_override is False:
                active_profile.enable_gamescope_wsi = False

        return active_profile

    def open_terminal(self, profile: Profile, instance_num: int) -> None:
        """Use the individual Start flow, replacing only Steam with a terminal."""
        # Detect on the host as Flatpak's PATH does not contain desktop terminals.
        terminals = {
            "konsole": ["--separate", "-e"],
            "gnome-terminal": ["--wait", "--"],
            "kgx": ["--"],
            "xfce4-terminal": ["--disable-server", "-x"],
            "mate-terminal": ["--disable-factory", "-x"],
            "kitty": [],
            "alacritty": ["-e"],
            "foot": ["--"],
            "x-terminal-emulator": ["-e"],
            "xterm": ["-e"],
        }
        result = Utils.flatpak_spawn_host(
            ["sh", "-c", 'for terminal do command -v "$terminal" && exit 0; done; exit 1', "sh", *terminals],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise DependencyError("No supported terminal found. Install Konsole, GNOME Terminal, or xterm.")
        terminal = result.stdout.strip().splitlines()[0]
        terminal_args = terminals.get(Path(terminal).name)
        if terminal_args is None:
            raise DependencyError(f"Terminal '{terminal}' is not supported by Twinverse.")

        active_profile = self._prepare_launch_profile(profile, use_gamescope_override=False)
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        command, instance_env = self._prepare_instance_launch(
            active_profile, instance_num, application_command=[terminal, *terminal_args, "bash", "-i"]
        )
        self.logger.info(f"Opening terminal for instance {instance_num}: {shlex.join(command)}")
        if Utils.is_flatpak():
            self._launch_in_flatpak(instance_num, command, instance_env)
        else:
            self._launch_natively(instance_num, command, instance_env)

    @staticmethod
    def _collect_wine_devices(pgid: int) -> list[int]:
        """
        Return the Wine helpers that descend from one instance.

        The list is collected before the instance is killed, because the
        helpers are reparented once their parent is gone and could not be
        recognized afterwards.
        """
        pids = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if "winedevice" not in cmdline:
                continue
            if not InstanceService._descends_from_group(int(entry.name), pgid):
                continue
            pids.append(int(entry.name))
        return pids

    @staticmethod
    def _descends_from_group(pid: int, pgid: int) -> bool:
        """Report whether a process descends from the given process group."""
        seen = set()
        current = pid
        while current > 1 and current not in seen:
            seen.add(current)
            try:
                if os.getpgid(current) == pgid:
                    return True
                status = Path(f"/proc/{current}/status").read_text()
            except OSError:
                return False
            parent = 0
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                    break
            current = parent
        return False

    def _kill_wine_devices(self, instance_num: int, pids: list[int]) -> None:
        """
        Kill the Wine helpers of one instance.

        A host wide "pkill -f winedevice" would also take down the helpers of
        the other instances and of the Steam client of the user.
        """
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError) as e:
                self.logger.warning(f"Instance {instance_num}: Could not stop the Wine helper {pid}: {e}")
        if pids:
            self.logger.info(f"Instance {instance_num}: stopped {len(pids)} Wine helper(s) of this instance.")

    def terminate_instance(self, instance_num: int) -> None:
        """Terminates a single Steam instance gracefully."""
        if instance_num not in self.processes:
            self.logger.warning(f"Attempted to terminate non-existent instance {instance_num}")
            return

        process = self.processes[instance_num]
        self.logger.info(f"Terminating instance {process.pid}...")

        if process.poll() is None:
            # Get the appropriate process/group ID for termination.
            # For Flatpak, this is the host PGID we captured.
            # For native, it's the PGID we created.
            pgid = self.pgids.get(instance_num)
            if pgid:
                # The Wine helpers are collected while the process tree is
                # still intact, so only the ones of this instance are found.
                wine_devices = self._collect_wine_devices(pgid)
                if Utils.is_flatpak():
                    self.logger.info(f"Sending SIGTERM to host process group {pgid} for instance {instance_num}")
                    Utils.flatpak_spawn_host(["sh", "-c", f"kill -15 -{pgid}"])
                else:
                    try:
                        self.logger.info(f"Sending SIGTERM to process group {pgid} for instance {instance_num}")
                        os.killpg(pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        self.logger.warning(f"Process group {pgid} not found for instance {instance_num}.")

                try:
                    process.wait(timeout=10)
                    self.logger.info(f"Instance {instance_num} terminated gracefully.")
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"Instance {instance_num} did not terminate after 10s. Sending SIGKILL.")
                    if Utils.is_flatpak():
                        try:
                            Utils.flatpak_spawn_host(["sh", "-c", f"kill -9 -{pgid}"])
                        except Exception as e:
                            self.logger.warning(f"Failed to send SIGKILL to host PGID {pgid}: {e}")

                        self.logger.info(f"Instance {instance_num} terminated with SIGKILL.")
                    else:
                        try:
                            os.killpg(pgid, signal.SIGKILL)
                        except ProcessLookupError:
                            self.logger.warning(
                                f"Process group {pgid} not found when sending SIGKILL for instance {instance_num}."
                            )
                        except PermissionError as e:
                            self.logger.error(f"Permission denied when sending SIGKILL to process group {pgid}: {e}")
                            raise TwinverseError(f"Permission denied when terminating instance {instance_num}: {e}")

                        self.logger.info(f"Instance {instance_num} terminated with SIGKILL.")

                    # This is necessary as a temporary measure for the problem described in:
                    # https://github.com/ValveSoftware/gamescope/issues/1482
                    self._kill_wine_devices(instance_num, wine_devices)
            else:
                self.logger.warning(f"No PGID found for instance {instance_num}, cannot send termination signal.")

        if process.poll() is None:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.logger.warning(f"Instance {instance_num} is still running after the termination request.")
                process.kill()
                process.wait()

        if instance_num in self.processes:
            del self.processes[instance_num]
        if instance_num in self.pids:
            del self.pids[instance_num]
        if instance_num in self.pgids:
            del self.pgids[instance_num]

    def _prepare_home(self, home_path: Path) -> None:
        """
        Prepare the isolated Steam directories for the instance.

        Args:
            home_path: The instance home to populate.
        """
        self.logger.info(f"Preparing isolated Steam directories for instance at {home_path}...")

        sdbx_steam_local = home_path / ".local/share/Steam"

        try:
            (sdbx_steam_local / "steamapps").mkdir(parents=True, exist_ok=True)
            (sdbx_steam_local / "compatibilitytools.d").mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            self.logger.error(f"Permission denied when creating Steam directories: {e}")
            raise TwinverseError(f"Permission denied when creating Steam directories: {e}")
        except OSError as e:
            self.logger.error(f"OS error when creating Steam directories: {e}")
            raise TwinverseError(f"OS error when creating Steam directories: {e}")

        self.logger.info("Isolated Steam directories are ready.")

    def _sync_app_manifests(self, home_path: Path) -> None:
        """Copy host manifests before removing obsolete instance manifests."""
        host_steamapps = Path.home() / ".local/share/Steam/steamapps"
        dest_steamapps = home_path / ".local/share/Steam/steamapps"

        # Use iterdir rather than glob so inaccessible sources raise an error.
        try:
            manifests = [path for path in host_steamapps.iterdir() if path.suffix == ".acf"]
        except OSError as e:
            self.logger.warning(
                f"Cannot read host Steam directory '{host_steamapps}'; preserving instance manifests: {e}"
            )
            return

        if not manifests:
            # An empty host library means the games live somewhere else, so
            # the manifests of the instance are kept instead of being wiped.
            self.logger.warning(
                f"Host Steam directory '{host_steamapps}' has no game manifests; preserving instance manifests."
            )
            return

        try:
            for manifest in manifests:
                shutil.copy(manifest, dest_steamapps / manifest.name)

            host_names = {manifest.name for manifest in manifests}
            for manifest in dest_steamapps.iterdir():
                if manifest.suffix == ".acf" and manifest.name not in host_names:
                    manifest.unlink()
        except OSError as e:
            raise TwinverseError(f"Failed to synchronize Steam app manifests: {e}") from e

    def _prepare_environment(self, profile: Profile, device_info: dict, instance_num: int) -> dict:
        """Prepare a dictionary of environment variables for the Steam instance."""
        env = {}

        env["ENABLE_GAMESCOPE_WSI"] = "1" if profile.enable_gamescope_wsi else "0"

        if device_info.get("audio_device_id_for_instance"):
            env["PULSE_SINK"] = device_info["audio_device_id_for_instance"]
            self.logger.info(
                f"Instance {instance_num}: Setting PULSE_SINK to '{device_info['audio_device_id_for_instance']}'."
            )

        # Custom ENV variables from the profile are set via bwrap --setenv, so we don't handle them here.

        self.logger.info(f"Instance {instance_num}: Environment variables prepared.")
        return env

    def _validate_input_devices(self, profile: Profile, instance_num: int, instance_num_display: int) -> dict:
        """Validate input devices and return information about them."""
        player_config = (
            profile.player_configs[instance_num]
            if profile.player_configs and 0 <= instance_num < len(profile.player_configs)
            else PlayerInstanceConfig()  # Default empty config
        )

        def _validate_device(path_str: Optional[str], device_type: str) -> Optional[str]:
            if not path_str or not path_str.strip():
                return None
            path_obj = Path(path_str)
            if path_obj.exists() and path_obj.is_char_device():
                self.logger.info(f"Instance {instance_num_display}: {device_type} device '{path_str}' assigned.")
                return str(path_obj.resolve())
            self.logger.warning(
                f"Instance {instance_num_display}: {device_type} device '{path_str}' not found or not a char device."
            )
            return None

        joystick_path = _validate_device(player_config.physical_device_id, "Joystick")

        audio_id = player_config.audio_device_id
        if audio_id and audio_id.strip():
            self.logger.info(f"Instance {instance_num_display}: Audio device ID '{audio_id}' assigned.")

        return {
            "joystick_path_str_for_instance": joystick_path,
            "audio_device_id_for_instance": (audio_id if audio_id and audio_id.strip() else None),
            "should_add_grab_flags": player_config.grab_input_devices,
        }

    def terminate_all(self) -> None:
        """Terminate all managed steam instances."""
        if self.termination_in_progress:
            return
        try:
            self.termination_in_progress = True
            self.logger.info("Starting termination of all instances...")

            if self._virtual_joystick_path:
                self.virtual_device.destroy_virtual_joystick()
                self._virtual_joystick_path = None
                self.logger.info("Virtual joystick destroyed.")
            self._virtual_joystick_checked = False

            if self.kde_manager:
                self.kde_manager.stop_kwin_script()
                self.kde_manager.restore_panel_states()
                self.logger.info("KDE-specific cleanup complete.")

            # A failure with one instance must not leave the others running.
            for instance_num in list(self.processes.keys()):
                try:
                    self.terminate_instance(instance_num)
                except Exception as e:
                    self.logger.error(f"Could not terminate instance {instance_num}: {e}")
                    self.logger.exception("Exception details:")

            self.logger.info("Instance termination complete.")
            # The instances remove themselves from the tracking, so an entry
            # that is still listed belongs to a launch that is in progress.
            for instance_num in list(self.processes.keys()):
                self.processes.pop(instance_num, None)
                self.pids.pop(instance_num, None)
                self.pgids.pop(instance_num, None)

        finally:
            self.termination_in_progress = False
