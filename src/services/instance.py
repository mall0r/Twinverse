"""Launch, termination and configuration of Steam instances in isolated environments."""

import copy
import ipaddress
import logging
import os
import shlex
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core import Config, Utils
from src.core.exceptions import DependencyError, TwinverseError, VirtualDeviceError
from src.core.logging import InstanceLog, get_logging_handle, get_run_id, log_context
from src.models import PlayerInstanceConfig, Profile

from .instance_registry import (
    FLATPAK,
    NATIVE,
    InstanceProbe,
    InstanceRecord,
    InstanceRegistry,
    ProcessHandle,
    RecoveredInstance,
)
from .kde_manager import KdeManager
from .network import network_command
from .steam_probe import ClientUpdate, SteamClientProbe

logger = logging.getLogger(__name__)


def _instance_log_limit() -> int:
    """Return the configured size cap for one instance log."""
    handle = get_logging_handle()
    if handle is None:
        return 100 * 1024 * 1024
    return handle.settings.instance_max_bytes


class InstanceService:
    """Tracks the process, PGID and Popen of every managed instance."""

    _GRACEFUL_TERMINATION_TIMEOUT = 10.0

    def __init__(self, kde_manager: Optional[KdeManager] = None):
        """Initialize the instance service."""
        from .device_manager import DeviceManager
        from .virtual_device import VirtualDeviceService

        self.virtual_device = VirtualDeviceService()
        self.kde_manager = kde_manager
        self.device_manager = DeviceManager()
        self._virtual_joystick_path: Optional[str] = None
        self._virtual_joystick_checked: bool = False
        self.pids: dict[int, int] = {}
        self.pgids: dict[int, int] = {}
        self.processes: dict[int, ProcessHandle] = {}
        self.termination_in_progress = False

        self._registry = InstanceRegistry()
        self._probe = InstanceProbe()
        self.recovered_instances: list[InstanceRecord] = []
        self._recover_instances()

    def _recover_instances(self) -> list[InstanceRecord]:
        """Find the instances that outlived the session that launched them."""
        registry = getattr(self, "_registry", None)
        if registry is None:
            return []

        records = registry.load()
        if not records:
            return []

        surviving = []
        for record in records:
            if self._probe.alive(record):
                surviving.append(record)
            else:
                logger.info(
                    "Instance %s of the previous session is not running anymore",
                    record.instance + 1,
                )
        registry.save(surviving)

        for record in surviving:
            self.processes[record.instance] = RecoveredInstance(record, self._probe)
            self.pids[record.instance] = record.pgid
            self.pgids[record.instance] = record.pgid

        if surviving:
            logger.warning(
                "%s instance(s) of the previous session are still running: %s. "
                "They can be stopped with the stop button.",
                len(surviving),
                ", ".join(str(record.instance + 1) for record in surviving),
            )
        self.recovered_instances = surviving
        return surviving

    def _record_instance(self, instance_num: int, instance_log: Optional[InstanceLog]) -> None:
        """Remember an instance, so a later session is able to find it."""
        registry = getattr(self, "_registry", None)
        if registry is None:
            return
        pgid = self.pgids.get(instance_num)
        if pgid is None:
            return
        registry.add(
            InstanceRecord(
                instance=instance_num,
                pgid=pgid,
                pid=self.pids.get(instance_num),
                mode=FLATPAK if Utils.is_flatpak() else NATIVE,
                home=str(Config.get_steam_home_path(instance_num)),
                log=str(instance_log.path) if instance_log is not None and instance_log.path else None,
                started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                run_id=get_run_id(),
            )
        )

    def _forget_instance(self, instance_num: int) -> None:
        """Forget an instance that is not running anymore."""
        SteamClientProbe(instance_num).clear_status()
        offsets = getattr(self, "_client_log_offsets", None)
        if offsets is not None:
            offsets.pop(instance_num, None)
        percents = getattr(self, "_client_log_percents", None)
        if percents is not None:
            percents.pop(instance_num, None)
        registry = getattr(self, "_registry", None)
        if registry is None:
            return
        self._probe.forget(instance_num)
        registry.remove(instance_num)

    def finish_instance_log(self, instance_num: int, exit_code: Optional[int] = None) -> None:
        """Close the log of an instance that is not running anymore."""
        instance_log = self.instance_logs.pop(instance_num, None)
        if instance_log is not None:
            instance_log.finish(exit_code=exit_code)
            logger.info(
                "Instance %s log finished (exit_code=%s): %s",
                instance_num + 1,
                exit_code,
                instance_log.path or "unavailable",
            )

    def _cleanup_shared_resources(self) -> None:
        """Release shared session resources once no managed instances remain."""
        if getattr(self, "_virtual_joystick_path", None):
            self.virtual_device.destroy_virtual_joystick()
            self._virtual_joystick_path = None
        self._virtual_joystick_checked = False

        kde_manager = getattr(self, "kde_manager", None)
        if kde_manager:
            kde_manager.stop_kwin_script()
            kde_manager.restore_panel_states()
            logger.info("KDE-specific cleanup complete.")

    def cleanup_stopped_instance(self, instance_num: int, exit_code: Optional[int] = None) -> None:
        """Clean up tracking and shared resources for an instance that exited on its own."""
        with log_context(instance=instance_num + 1):
            process = self.processes.pop(instance_num, None)
            self.pids.pop(instance_num, None)
            self.pgids.pop(instance_num, None)
            if exit_code is None and process is not None:
                exit_code = process.poll()
            self.finish_instance_log(instance_num, exit_code=exit_code)
            self._forget_instance(instance_num)
            if not self.processes and not getattr(self, "termination_in_progress", False):
                self._cleanup_shared_resources()

    def is_client_up(self, instance_num: int) -> bool:
        """
        Report whether the Steam client of an instance is running.

        The check is scoped by the process group of the instance, so the
        client of another instance, and the Steam of the user, are never
        taken for ours.
        """
        pgid = self.pgids.get(instance_num)
        if pgid is None:
            return False
        return SteamClientProbe(instance_num).is_client_up(pgid)

    def client_status(self, instance_num: int) -> ClientUpdate:
        """
        Return what the Steam client is doing and the reason it gave up.

        The log of the client is read from the last place it was read, so a
        long update does not make every check read the whole log again. The
        percentage of the last update that gave one is kept, so the bar does
        not lose the progress when the client writes a step without a
        percentage.
        """
        offsets = getattr(self, "_client_log_offsets", None)
        if offsets is None:
            offsets = {}
            self._client_log_offsets = offsets

        percents = getattr(self, "_client_log_percents", None)
        if percents is None:
            percents = {}
            self._client_log_percents = percents

        probe = SteamClientProbe(instance_num)
        current_size = probe.client_log_size()
        since = offsets.get(instance_num)
        if since is None:
            since = current_size
        elif current_size < since:
            # Steam rotated or truncated its log; read from the start of the new file.
            since = 0
        update = probe.read_updates(since)
        offsets[instance_num] = probe.client_log_size()

        if update.percent is not None:
            percents[instance_num] = update.percent
        elif instance_num in percents:
            update = update._replace(percent=percents[instance_num])
        return update

    @property
    def instance_logs(self) -> dict[int, InstanceLog]:
        """Return the log handles of the instances launched by this service."""
        logs = getattr(self, "_instance_logs", None)
        if logs is None:
            logs = {}
            self._instance_logs = logs
        return logs

    @staticmethod
    def _configured_guest_address(profile: Profile, instance_num: int) -> Optional[str]:
        """Return the guest address chosen for one instance, if one is valid.

        An empty value leaves the choice to the host network setup, which
        picks a free address in the subnet. A value without a prefix is
        completed with the prefix of the host interface.
        """
        if not 0 <= instance_num < len(profile.player_configs):
            return None
        value = (profile.player_configs[instance_num].guest_ip or "").strip()
        if not value:
            return None
        try:
            if "/" in value:
                ipaddress.IPv4Interface(value)
            else:
                ipaddress.IPv4Address(value)
        except ValueError:
            logger.warning(
                "Instance %s: invalid GUEST_IP %r; selecting a free address instead",
                instance_num + 1,
                value,
            )
            return None
        return value

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
        logger.info("Instance %s: Using isolated home path '%s'", instance_num + 1, home_path)

        self._prepare_home(home_path)
        if application_command is None:
            self._sync_app_manifests(home_path)

        device_info = self._validate_input_devices(profile, instance_num, instance_num + 1)
        instance_env = self._prepare_environment(profile, device_info, instance_num)

        from .cmd_builder import CommandBuilder

        cmd_builder = CommandBuilder(
            profile,
            device_info,
            self.device_manager,
            instance_num,
            home_path,
            self._virtual_joystick_path,
        )
        instance_env.update(cmd_builder.prepare_overlay_environment())
        command = cmd_builder.build_command(application_command)
        bridge_cmds = getattr(self, "_pending_bridge_commands", None)
        if bridge_cmds is None:
            bridge_cmds = {}
            self._pending_bridge_commands = bridge_cmds
        if cmd_builder.input_bridge_command:
            bridge_cmds[instance_num] = cmd_builder.input_bridge_command
        else:
            bridge_cmds.pop(instance_num, None)
        return command, instance_env

    def _pop_bridge_command(self, instance_num: int) -> Optional[list[str]]:
        """Return and clear any prepared input bridge supervisor command for ``instance_num``."""
        bridge_cmds = getattr(self, "_pending_bridge_commands", None)
        if bridge_cmds is None:
            return None
        return bridge_cmds.pop(instance_num, None)

    def _launch_single_instance(self, profile: Profile, instance_num: int) -> None:
        """Launch a single steam instance."""
        with log_context(instance=instance_num + 1):
            logger.info("Preparing instance %s", instance_num + 1)

            base_command, instance_env = self._prepare_instance_launch(profile, instance_num)
            bridge_command = self._pop_bridge_command(instance_num)
            guest_address = self._configured_guest_address(profile, instance_num) if profile.isolate_network else None
            instance_log = InstanceLog.create(
                instance_num,
                command=base_command,
                env_keys=instance_env.keys(),
                cwd=Path.home(),
                max_bytes=_instance_log_limit(),
            )
            logger.info("Launching instance %s (log: %s)", instance_num + 1, instance_log.path or "disabled")
            logger.debug("Environment keys: %s", ", ".join(sorted(instance_env)))
            self.instance_logs[instance_num] = instance_log
            probe = SteamClientProbe(instance_num)
            probe.clear_status()
            offsets = getattr(self, "_client_log_offsets", None)
            if offsets is None:
                offsets = {}
                self._client_log_offsets = offsets
            offsets[instance_num] = probe.client_log_size()
            percents = getattr(self, "_client_log_percents", None)
            if percents is not None:
                percents.pop(instance_num, None)

            try:
                if Utils.is_flatpak():
                    logger.info("Launching instance %s in the Flatpak environment", instance_num + 1)
                    process, pgid = self._launch_in_flatpak(
                        instance_num,
                        base_command,
                        instance_env,
                        log=instance_log,
                        guest_address=guest_address,
                        isolate_network=profile.isolate_network,
                        bridge_command=bridge_command,
                    )
                else:
                    logger.info("Launching instance %s natively", instance_num + 1)
                    process, pgid = self._launch_natively(
                        instance_num,
                        base_command,
                        instance_env,
                        log=instance_log,
                        guest_address=guest_address,
                        isolate_network=profile.isolate_network,
                        bridge_command=bridge_command,
                    )

                self.pids[instance_num] = process.pid
                self.pgids[instance_num] = pgid
                self.processes[instance_num] = process

                logger.info("Instance %s launched with PID %s", instance_num + 1, process.pid)
                self._record_instance(instance_num, instance_log)

            except TwinverseError:
                instance_log.finish(exit_code=1)
                self.instance_logs.pop(instance_num, None)
                logger.exception("Instance %s failed to launch", instance_num + 1)
                raise
            except Exception as error:
                instance_log.finish(exit_code=1)
                self.instance_logs.pop(instance_num, None)
                logger.exception("Instance %s failed with an unexpected error", instance_num + 1)
                raise TwinverseError(f"Failed to launch instance {instance_num}: {error}") from error

    def _launch_in_flatpak(
        self,
        instance_num: int,
        base_command: list[str],
        instance_env: dict,
        log: Optional[InstanceLog] = None,
        guest_address: Optional[str] = None,
        isolate_network: bool = True,
        bridge_command: Optional[list[str]] = None,
    ) -> tuple[subprocess.Popen, int]:
        """Launch a Steam instance within a Flatpak environment."""
        if log is None:
            log = InstanceLog.create(
                instance_num,
                command=base_command,
                env_keys=instance_env,
                cwd=Path.home(),
                max_bytes=_instance_log_limit(),
            )
        env_prefix_parts = [
            f"unset {shlex.quote(key)}" if value is None else f"export {shlex.quote(key)}={shlex.quote(value)}"
            for key, value in instance_env.items()
        ]
        env_prefix = "; ".join(env_prefix_parts) + "; " if env_prefix_parts else ""
        escaped_command = shlex.join(base_command)
        # The instance writes straight to its log file, the same way the native
        # launch does. A pipe would break as soon as the application dies and
        # would stop the output of an instance that outlives it.
        redirect = f" >> {shlex.quote(str(log.path))} 2>&1" if log.path is not None else ""
        # The shell reports the process group it leads, so the instance can be
        # stopped as a group on the host.
        #
        # The watcher runs here as well, on the host, and reports the state of
        # the Steam client in a file that the application reads. It keeps the
        # application inside the sandbox: it never has to ask the host about
        # the processes of the instance.
        watcher = SteamClientProbe(instance_num).watcher_script()
        bridge_prefix = f"{shlex.join(bridge_command)} -- " if bridge_command else ""
        if isolate_network:
            network_launch = shlex.join(network_command(base_command, guest_address, instance_num))
            inner_script = (
                f"echo $$; {watcher} "
                f"if command -v pasta >/dev/null 2>&1; then exec {bridge_prefix}{network_launch}; "
                f"else exec {bridge_prefix}{escaped_command}; fi{redirect}"
            )
        else:
            logger.info("Instance %s: network isolation disabled; sharing host network", instance_num + 1)
            inner_script = f"echo $$; {watcher} exec {bridge_prefix}{escaped_command}{redirect}"
        # The instance leads its own process group, so it can be signalled as
        # a whole and its children go down with it.
        bash_path = shutil.which("bash") or "/bin/bash"
        setsid_path = shutil.which("setsid")
        if setsid_path:
            leader = f"exec {setsid_path} -w {bash_path} -c {shlex.quote(inner_script)}"
        else:
            leader = f"exec {bash_path} -c {shlex.quote(inner_script)}"
        shell_command = f"{env_prefix}{leader}"

        logger.info("Instance %s full command: %s", instance_num + 1, escaped_command)
        logger.debug("Instance %s host shell command: %s", instance_num + 1, shell_command)

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
        except FileNotFoundError as error:
            logger.exception("flatpak-spawn-host command not found")
            raise DependencyError(f"flatpak-spawn-host command not found: {error}") from error
        except PermissionError as error:
            logger.exception("Permission denied when spawning the host process")
            raise TwinverseError(f"Permission denied when launching instance {instance_num}: {error}") from error
        except Exception as error:
            logger.exception("Unexpected error when spawning the host process")
            raise TwinverseError(f"Unexpected error when launching instance {instance_num}: {error}") from error

        time.sleep(0.1)

        if process.poll() is not None:
            stdout_data, stderr_data = process.communicate()
            log.write(stdout_data or b"")
            log.write(stderr_data or b"")
            log.finish(exit_code=process.returncode)
            stdout_str = stdout_data.decode(errors="replace") if stdout_data else ""
            stderr_str = stderr_data.decode(errors="replace") if stderr_data else ""
            error_message = (
                f"STDOUT: {stdout_str}\nSTDERR: {stderr_str}" if (stdout_str or stderr_str) else "Unknown error"
            )
            logger.error("Instance %s process failed to start:\n%s", instance_num + 1, error_message)
            raise DependencyError(f"Command failed to start: {base_command[0]} - {error_message}")

        pgid_str = process.stdout.readline().decode(errors="replace").strip() if process.stdout else ""
        if pgid_str.isdigit():
            pgid = int(pgid_str)
            # The instance writes to its log file on its own. The pipes only
            # carry what the launcher itself writes, and are drained so that
            # they can never fill up and block the instance.
            if process.stdout:
                log.start_drain(process.stdout)
            if process.stderr:
                log.start_drain(process.stderr)
            logger.info(
                "Instance %s started on the host with PID %s and host PGID %s",
                instance_num + 1,
                process.pid,
                pgid,
            )
            return process, pgid

        logger.error("Instance %s: failed to capture the host PGID; read %r", instance_num + 1, pgid_str)
        process.terminate()

        stdout_data, stderr_data = process.communicate(timeout=1) if process.stdout else (None, None)
        log.write(stdout_data or b"")
        log.write(stderr_data or b"")
        log.finish(exit_code=process.returncode)
        stdout_str = stdout_data.decode(errors="replace") if stdout_data else ""
        stderr_str = stderr_data.decode(errors="replace") if stderr_data else ""
        error_message = (
            f"STDOUT: {stdout_str}\nSTDERR: {stderr_str}"
            if (stdout_str or stderr_str)
            else "Failed to capture host PGID"
        )

        raise TwinverseError(f"Failed to get host process group ID for instance {instance_num}: {error_message}")

    def _launch_natively(
        self,
        instance_num: int,
        base_command: list[str],
        instance_env: dict,
        log: Optional[InstanceLog] = None,
        guest_address: Optional[str] = None,
        isolate_network: bool = True,
        bridge_command: Optional[list[str]] = None,
    ) -> tuple[subprocess.Popen, int]:
        """Launch a Steam instance natively."""
        if log is None:
            log = InstanceLog.create(
                instance_num,
                command=base_command,
                env_keys=instance_env,
                cwd=Path.home(),
                max_bytes=_instance_log_limit(),
            )
        native_env = os.environ.copy()
        native_env.pop("PYTHONHOME", None)
        native_env.pop("PYTHONPATH", None)
        for key, value in instance_env.items():
            if value is None:
                native_env.pop(key, None)
            else:
                native_env[key] = value

        logger.info("Instance %s full command: %s", instance_num + 1, shlex.join(base_command))
        logger.debug("Instance %s environment keys: %s", instance_num + 1, list(instance_env))

        if not shutil.which(base_command[0]):
            error_msg = f"Command '{base_command[0]}' not found in PATH"
            logger.error("Instance %s: %s", instance_num + 1, error_msg)
            raise DependencyError(error_msg)

        if isolate_network:
            if shutil.which("pasta"):
                base_command = network_command(base_command, guest_address, instance_num)
        else:
            logger.info("Instance %s: network isolation disabled; sharing host network", instance_num + 1)

        if bridge_command:
            base_command = [*bridge_command, "--", *base_command]

        try:
            # The output goes straight to the instance log, so a chatty Steam
            # or Proton session can never fill a pipe and block the instance.
            output = log.open_stream()
        except OSError as error:
            logger.exception("Instance %s: could not open the instance log", instance_num + 1)
            raise TwinverseError(f"Could not open the instance log for instance {instance_num}: {error}") from error

        try:
            process = subprocess.Popen(
                base_command,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=native_env,
                cwd=Path.home(),
                preexec_fn=os.setpgrp,
            )
        except FileNotFoundError as error:
            log.finish(exit_code=127)
            logger.exception("Instance %s: command not found", instance_num + 1)
            raise DependencyError(f"Command not found: {error}") from error
        except PermissionError as error:
            log.finish(exit_code=126)
            logger.exception("Instance %s: permission denied", instance_num + 1)
            raise TwinverseError(f"Permission denied when launching instance {instance_num}: {error}") from error
        except OSError as error:
            log.finish(exit_code=1)
            logger.exception("Instance %s: OS error when launching", instance_num + 1)
            raise TwinverseError(f"OS error when launching instance {instance_num}: {error}") from error
        finally:
            # The child keeps its own copy of the descriptor.
            try:
                output.close()
            except OSError:
                pass

        time.sleep(0.1)

        if process.poll() is not None:
            error_message = log.tail() or "Unknown error"
            log.finish(exit_code=process.returncode)
            logger.error("Instance %s process failed to start:\n%s", instance_num + 1, error_message)
            raise DependencyError(f"Command failed to start: {base_command[0]} - {error_message}")

        pgid = process.pid
        logger.info("Instance %s started with PID %s and PGID %s", instance_num + 1, process.pid, pgid)
        return process, pgid

    def launch_instance(
        self,
        profile: Profile,
        instance_num: int,
        use_gamescope_override: Optional[bool] = None,
    ) -> None:
        """Launch a single Steam instance."""
        active_profile = self._prepare_launch_profile(profile, use_gamescope_override)
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
                logger.info("One or more instances lack a physical joystick. Creating a virtual one.")
                try:
                    self._virtual_joystick_path = self.virtual_device.create_virtual_joystick()
                except VirtualDeviceError as e:
                    logger.error(f"Halting launch due to virtual joystick creation failure: {str(e)}")
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
        command, instance_env = self._prepare_instance_launch(
            active_profile, instance_num, application_command=[terminal, *terminal_args, "bash", "-i"]
        )
        with log_context(instance=instance_num + 1, phase="terminal"):
            instance_log = InstanceLog.create(
                instance_num,
                command=command,
                env_keys=instance_env.keys(),
                cwd=Path.home(),
                max_bytes=_instance_log_limit(),
            )
            guest_address = (
                self._configured_guest_address(active_profile, instance_num) if active_profile.isolate_network else None
            )
            bridge_command = self._pop_bridge_command(instance_num)
            logger.info("Opening a terminal for instance %s: %s", instance_num + 1, shlex.join(command))
            if Utils.is_flatpak():
                self._launch_in_flatpak(
                    instance_num,
                    command,
                    instance_env,
                    log=instance_log,
                    guest_address=guest_address,
                    isolate_network=active_profile.isolate_network,
                    bridge_command=bridge_command,
                )
            else:
                self._launch_natively(
                    instance_num,
                    command,
                    instance_env,
                    log=instance_log,
                    guest_address=guest_address,
                    isolate_network=active_profile.isolate_network,
                    bridge_command=bridge_command,
                )

    @staticmethod
    def _read_proc_info(pid_str: str) -> Optional[tuple[int, int, int, str, int]]:
        """Return ``(pid, ppid, pgrp, state, starttime)`` from ``/proc/<pid>/stat``, or None."""
        try:
            stat = Path(f"/proc/{pid_str}/stat").read_text()
        except OSError:
            return None
        open_paren = stat.find("(")
        close_paren = stat.rfind(")")
        if open_paren == -1 or close_paren <= open_paren:
            return None
        fields = stat[close_paren + 1 :].split()
        if len(fields) < 20:
            return None
        try:
            return int(pid_str), int(fields[1]), int(fields[2]), fields[0], int(fields[19])
        except ValueError:
            return None

    @classmethod
    def _collect_instance_pids(cls, pgid: int, seed_pids: Optional[dict[int, int]] = None) -> dict[int, int]:
        """Return ``{pid: starttime}`` strictly for live descendants of ``pgid``.

        Inside SteamRT3, pressure-vessel (``pv-adverb``, ``srt-bwrap``) and
        ``steamwebhelper`` call ``setsid()``, moving into new process groups
        outside ``pgid``. Walking only the parent-child tree rooted at ``pgid``
        (and carrying verified ``(pid, starttime)`` seeds across shutdown ticks)
        stops every sub-session child without ever touching other instances or
        any host session process.
        """
        self_pid = os.getpid()
        self_ppid = os.getppid()
        self_pgid = os.getpgrp()
        if pgid <= 1 or pgid == self_pgid:
            return {}

        try:
            entries = list(Path("/proc").iterdir())
        except OSError:
            return {}

        procs: dict[int, tuple[int, int, str, int]] = {}
        children: dict[int, list[int]] = {}
        queue: list[int] = []
        visited: set[int] = set()

        for entry in entries:
            if not entry.name.isdigit():
                continue
            parsed = cls._read_proc_info(entry.name)
            if parsed is None:
                continue
            pid, ppid, pgrp, state, starttime = parsed
            if pid <= 1 or pid == self_pid or pid == self_ppid or pgrp == self_pgid:
                continue
            procs[pid] = (ppid, pgrp, state, starttime)
            children.setdefault(ppid, []).append(pid)
            is_group_member = pgrp == pgid
            is_seed_member = seed_pids is not None and seed_pids.get(pid) == starttime
            if (is_group_member or is_seed_member) and pid not in visited:
                visited.add(pid)
                queue.append(pid)

        while queue:
            current = queue.pop()
            for child in children.get(current, ()):
                if child not in visited:
                    visited.add(child)
                    queue.append(child)

        return {pid: procs[pid][3] for pid in visited if pid in procs and procs[pid][2] != "Z"}

    @classmethod
    def _signal_pids(cls, pids: dict[int, int], sig: int, exclude_pgid: Optional[int] = None) -> None:
        """Send a signal to tracked PIDs whose start times still match."""
        self_pid = os.getpid()
        self_ppid = os.getppid()
        self_pgid = os.getpgrp()
        for pid, expected_starttime in pids.items():
            if pid <= 1 or pid == self_pid or pid == self_ppid:
                continue
            parsed = cls._read_proc_info(str(pid))
            if parsed is None:
                continue
            _, _, pgrp, state, starttime = parsed
            if state == "Z" or starttime != expected_starttime or pgrp == self_pgid:
                continue
            if exclude_pgid is not None and pgrp == exclude_pgid:
                continue
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

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
                logger.warning("Instance %s: Could not stop the Wine helper %s: %s", instance_num + 1, pid, e)
        if pids:
            logger.info("Instance %s: stopped %s Wine helper(s) of this instance.", instance_num + 1, len(pids))

    def _terminate_native_instance(
        self,
        instance_num: int,
        process: ProcessHandle,
        pgid: int,
        tracked: dict[int, int],
        wine_devices: list[int],
    ) -> None:
        """Terminate a native instance's process group and all sub-session descendants."""
        display_num = instance_num + 1
        if pgid <= 1 or pgid == os.getpgrp():
            logger.warning("Refusing to signal unsafe PGID %s for instance %s.", pgid, display_num)
            return

        logger.info("Sending SIGTERM to process group %s for instance %s", pgid, display_num)
        # Signal sub-session descendants (such as SteamRT3's pv-adverb / steam /
        # steamwebhelper) first so they begin graceful shutdown even if bwrap
        # exits immediately on SIGTERM.
        self._signal_pids(tracked, signal.SIGTERM, exclude_pgid=pgid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            logger.warning("Process group %s not found for instance %s.", pgid, display_num)

        timeout = getattr(self, "_GRACEFUL_TERMINATION_TIMEOUT", 10.0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            exited = process.poll() is not None
            tracked = self._collect_instance_pids(pgid, seed_pids=tracked)
            if exited and not tracked:
                logger.info("Instance %s terminated gracefully.", display_num)
                return
            time.sleep(0.1)

        logger.warning("Instance %s did not terminate after %gs. Sending SIGKILL.", display_num, timeout)
        tracked = self._collect_instance_pids(pgid, seed_pids=tracked)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            logger.warning("Process group %s not found when sending SIGKILL for instance %s.", pgid, display_num)
        except PermissionError as e:
            logger.error("Permission denied when sending SIGKILL to process group %s: %s", pgid, e)
            raise TwinverseError(f"Permission denied when terminating instance {display_num}: {e}")

        self._signal_pids(tracked, signal.SIGKILL)
        # This is necessary as a temporary measure for the problem described in:
        # https://github.com/ValveSoftware/gamescope/issues/1482
        self._kill_wine_devices(instance_num, wine_devices)

        kill_deadline = time.monotonic() + 2.0
        while time.monotonic() < kill_deadline:
            exited = process.poll() is not None
            tracked = self._collect_instance_pids(pgid, seed_pids=tracked)
            if tracked:
                self._signal_pids(tracked, signal.SIGKILL)
            if exited and not tracked:
                break
            time.sleep(0.05)

        logger.info("Instance %s terminated with SIGKILL.", display_num)

    @staticmethod
    def _build_flatpak_termination_script(pgid: int, timeout: float) -> str:
        """Build a host shell script that stops only ``pgid`` and its strict descendants.

        The AWK collector performs a read-only upward parent walk (`cur in root`)
        so it can never auto-vivify unrelated array entries or match any host
        process outside the instance's process tree.
        """
        target_pgid = int(pgid)
        timeout_ticks = max(1, int(timeout * 10))
        awk_program = shlex.quote(
            "BEGIN { "
            "target_g = g + 0; sp = self_pid + 0; spp = self_ppid + 0; spg = self_pgid + 0; "
            "if (target_g <= 1 || (spg > 1 && target_g == spg)) exit 0; "
            'n = split(seeds, arr, " "); '
            "for (i = 1; i <= n; i++) { "
            'idx = index(arr[i], ":"); '
            "if (idx > 1) { "
            "spid = substr(arr[i], 1, idx - 1) + 0; "
            "scomm = substr(arr[i], idx + 1); "
            'if (spid > 1 && scomm != "") seed_comm[spid] = scomm; '
            "} } } "
            "{ "
            "pid = $1 + 0; ppid = $2 + 0; pgrp = $3 + 0; st = $4; comm = $5; "
            "if (pid <= 1 || pid == sp || pid == spp) next; "
            "if (spg > 1 && pgrp == spg) next; "
            "p[pid] = ppid; c[pid] = comm; "
            'z[pid] = (substr(st, 1, 1) == "Z"); '
            "all[pid] = 1; "
            "if (pgrp == target_g) root[pid] = 1; "
            "if ((pid in seed_comm) && seed_comm[pid] == comm) root[pid] = 1; "
            "} "
            "END { "
            "for (k in all) { "
            "if (z[k]) continue; "
            "cur = k; steps = 0; "
            "while (cur > 1 && ++steps < 64) { "
            "if ((cur in root) && root[cur] == 1) { "
            'print k ":" c[k]; break; '
            "} "
            "if (!(cur in p)) break; "
            "cur = p[cur]; "
            "} } }"
        )
        return (
            "set -f; "
            f"g={target_pgid}; "
            '[ "$g" -gt 1 ] || exit 0; '
            "self_pid=$$; self_ppid=$PPID; "
            "self_pgid=$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' '); "
            '[ "$g" != "$self_pgid" ] || exit 0; '
            "collect() { "
            "ps -eo pid=,ppid=,pgid=,stat=,comm= 2>/dev/null | "
            'awk -v g="$g" -v self_pid="$self_pid" -v self_ppid="$self_ppid" '
            f'-v self_pgid="$self_pgid" -v seeds="$1" {awk_program}; '
            "}; "
            "signal_items() { "
            "local sig=$1 item p; shift; "
            "for item in $1; do "
            "p=${item%%:*}; "
            "case \"$p\" in ''|*[!0-9]*) continue ;; esac; "
            '[ "$p" -gt 1 ] || continue; '
            '[ "$p" != "$self_pid" ] && [ "$p" != "$self_ppid" ] || continue; '
            'kill -"$sig" "$p" 2>/dev/null || true; '
            "done; "
            "}; "
            "items=$(collect ''); "
            'signal_items TERM "$items"; '
            'kill -TERM -"$g" 2>/dev/null || true; '
            f"for ((i = 0; i < {timeout_ticks}; i++)); do "
            'items=$(collect "$items"); '
            'if ! kill -0 -"$g" 2>/dev/null && [ -z "$items" ]; then exit 0; fi; '
            "sleep 0.1; "
            "done; "
            'items=$(collect "$items"); '
            'kill -KILL -"$g" 2>/dev/null || true; '
            'signal_items KILL "$items"'
        )

    def _terminate_flatpak_instance(self, instance_num: int, process: ProcessHandle, pgid: int) -> None:
        """Terminate a Flatpak host instance's process group and all sub-session descendants."""
        display_num = instance_num + 1
        if pgid <= 1:
            logger.warning("Refusing to signal unsafe host PGID %s for instance %s.", pgid, display_num)
            return

        logger.info("Sending SIGTERM to host process group %s for instance %s", pgid, display_num)
        timeout = getattr(self, "_GRACEFUL_TERMINATION_TIMEOUT", 10.0)
        script = self._build_flatpak_termination_script(pgid, timeout)
        try:
            Utils.flatpak_spawn_host(["bash", "-c", script])
        except Exception as e:
            logger.warning("Failed to terminate host process tree for PGID %s: %s", pgid, e)

        try:
            process.wait(timeout=10)
            logger.info("Instance %s terminated gracefully.", display_num)
        except subprocess.TimeoutExpired:
            logger.warning("Instance %s did not terminate after 10s. Sending SIGKILL.", display_num)
            try:
                Utils.flatpak_spawn_host(["sh", "-c", f"kill -9 -{int(pgid)}"])
            except Exception as e:
                logger.warning("Failed to send SIGKILL to host PGID %s: %s", pgid, e)
            logger.info("Instance %s terminated with SIGKILL.", display_num)

    def terminate_instance(self, instance_num: int) -> None:
        """Terminate a single Steam instance and all of its sub-session processes."""
        display_num = instance_num + 1
        with log_context(instance=display_num):
            if instance_num not in self.processes:
                logger.warning("Attempted to terminate non-existent instance %s", display_num)
                return

            process = self.processes[instance_num]
            logger.info("Terminating instance %s (PID %s)...", display_num, process.pid)

            pgid = self.pgids.get(instance_num)
            if Utils.is_flatpak():
                if process.poll() is None:
                    if pgid:
                        self._terminate_flatpak_instance(instance_num, process, pgid)
                    else:
                        logger.warning("No PGID found for instance %s, cannot send termination signal.", display_num)
            else:
                # Collect the entire process tree while it is still intact so
                # sub-session processes (like SteamRT3's pv-adverb / steam /
                # steamwebhelper) remain tracked even after bwrap exits.
                tracked = self._collect_instance_pids(pgid) if pgid else {}
                if process.poll() is None or tracked:
                    if pgid:
                        wine_devices = self._collect_wine_devices(pgid)
                        self._terminate_native_instance(instance_num, process, pgid, tracked, wine_devices)
                    else:
                        logger.warning("No PGID found for instance %s, cannot send termination signal.", display_num)

            if process.poll() is None:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    logger.warning("Instance %s is still running after the termination request.", display_num)
                    process.kill()
                    process.wait()

            self.processes.pop(instance_num, None)
            self.pids.pop(instance_num, None)
            self.pgids.pop(instance_num, None)

            self.finish_instance_log(instance_num, exit_code=process.poll())
            self._forget_instance(instance_num)
            if not self.processes and not getattr(self, "termination_in_progress", False):
                self._cleanup_shared_resources()

    def _prepare_home(self, home_path: Path) -> None:
        """
        Prepare the isolated Steam directories for the instance.

        Args:
            home_path: The instance home to populate.
        """
        logger.info(f"Preparing isolated Steam directories for instance at {home_path}...")

        sdbx_steam_local = home_path / ".local/share/Steam"

        try:
            (sdbx_steam_local / "steamapps").mkdir(parents=True, exist_ok=True)
            (sdbx_steam_local / "compatibilitytools.d").mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            logger.error(f"Permission denied when creating Steam directories: {e}")
            raise TwinverseError(f"Permission denied when creating Steam directories: {e}")
        except OSError as e:
            logger.error(f"OS error when creating Steam directories: {e}")
            raise TwinverseError(f"OS error when creating Steam directories: {e}")

        logger.info("Isolated Steam directories are ready.")

    def _sync_app_manifests(self, home_path: Path) -> None:
        """Copy host manifests before removing obsolete instance manifests."""
        host_steamapps = Path.home() / ".local/share/Steam/steamapps"
        dest_steamapps = home_path / ".local/share/Steam/steamapps"

        # Use iterdir rather than glob so inaccessible sources raise an error.
        try:
            manifests = [path for path in host_steamapps.iterdir() if path.suffix == ".acf"]
        except OSError as e:
            logger.warning(f"Cannot read host Steam directory '{host_steamapps}'; preserving instance manifests: {e}")
            return

        if not manifests:
            # An empty host library means the games live somewhere else, so
            # the manifests of the instance are kept instead of being wiped.
            logger.warning(
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
            logger.info(
                "Instance %s: Setting PULSE_SINK to '%s'.",
                instance_num + 1,
                device_info["audio_device_id_for_instance"],
            )

        # Custom ENV variables from the profile are set via bwrap --setenv, so we don't handle them here.

        logger.info("Instance %s: Environment variables prepared.", instance_num + 1)
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
                logger.info(f"Instance {instance_num_display}: {device_type} device '{path_str}' assigned.")
                return str(path_obj.resolve())
            logger.warning(
                f"Instance {instance_num_display}: {device_type} device '{path_str}' not found or not a char device."
            )
            return None

        joystick_path = _validate_device(player_config.physical_device_id, "Joystick")

        audio_id = player_config.audio_device_id
        if audio_id and audio_id.strip():
            logger.info(f"Instance {instance_num_display}: Audio device ID '{audio_id}' assigned.")

        joystick_device_id = (
            player_config.physical_device_id.strip()
            if player_config.physical_device_id and player_config.physical_device_id.strip()
            else None
        )

        return {
            "joystick_path_str_for_instance": joystick_path,
            "joystick_device_id_for_instance": joystick_device_id,
            "audio_device_id_for_instance": (audio_id if audio_id and audio_id.strip() else None),
            "should_add_grab_flags": player_config.grab_input_devices,
        }

    def terminate_all(self) -> None:
        """Terminate all managed steam instances."""
        if self.termination_in_progress:
            return
        try:
            self.termination_in_progress = True
            logger.info("Starting termination of all instances...")

            self._cleanup_shared_resources()

            # A failure with one instance must not leave the others running.
            for instance_num in list(self.processes.keys()):
                try:
                    self.terminate_instance(instance_num)
                except Exception:
                    logger.exception("Could not terminate instance %s", instance_num + 1)

            logger.info("Instance termination complete.")
            # The instances remove themselves from the tracking, so an entry
            # that is still listed belongs to a launch that is in progress.
            for instance_num in list(self.processes.keys()):
                self.processes.pop(instance_num, None)
                self.pids.pop(instance_num, None)
                self.pgids.pop(instance_num, None)

        finally:
            self.termination_in_progress = False
