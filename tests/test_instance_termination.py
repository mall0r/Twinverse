"""Stop the instances without touching the other ones or the host."""

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.gui.controllers.launch_controller import LaunchController
from src.services.instance import InstanceService
from src.services.network import NETWORK_SETUP


def _controller(terminate=None):
    """Build a launch controller with a mocked instance service."""
    service = Mock()
    if terminate is not None:
        service.terminate_all.side_effect = terminate
    controller = LaunchController(service, Mock())
    return controller, service


def test_the_stop_always_finishes():
    """A failure while stopping must not leave the window locked."""
    controller, service = _controller(terminate=RuntimeError("boom"))
    finished = []

    controller.stop_instances(on_complete=lambda: finished.append(True))
    controller._stop_thread.join(timeout=5)

    assert finished == [True]


def test_the_cancel_flag_survives_the_stop():
    """The launch must not continue after the user asked it to stop."""
    controller, service = _controller()
    controller._launch_thread = Mock()
    controller._launch_thread.is_alive.return_value = True

    controller.stop_instances()
    controller._stop_thread.join(timeout=5)

    assert controller._cancel_event.is_set()


def test_a_new_launch_clears_the_cancel_flag():
    """The next launch starts from scratch."""
    controller, service = _controller()
    controller._cancel_event.set()
    controller.launch_instances(Mock())
    controller._launch_thread.join(timeout=5)

    assert not controller._cancel_event.is_set()


def test_the_wine_helpers_of_one_instance_are_found(tmp_path):
    """Only the helpers that belong to the instance are collected."""
    helper = tmp_path / "winedevice"
    helper.write_text("#!/bin/sh\nsleep 30\n")
    helper.chmod(0o755)

    other = subprocess.Popen(["sleep", "30"], start_new_session=True)
    mine = subprocess.Popen([str(helper)], start_new_session=True)
    try:
        found = InstanceService._collect_wine_devices(os.getpgid(mine.pid))
        assert mine.pid in found
        assert other.pid not in found
    finally:
        for process in (mine, other):
            process.kill()
            process.wait(timeout=5)


def test_the_wine_helpers_are_not_killed_outside_the_instance(tmp_path):
    """Stopping one instance leaves the helpers of the other ones alone."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()

    helper = tmp_path / "winedevice"
    helper.write_text("#!/bin/sh\nsleep 30\n")
    helper.chmod(0o755)

    other = subprocess.Popen(["sleep", "30"], start_new_session=True)
    mine = subprocess.Popen([str(helper)], start_new_session=True)
    try:
        found = InstanceService._collect_wine_devices(os.getpgid(mine.pid))
        service._kill_wine_devices(0, found)
        time.sleep(0.2)

        assert mine.poll() is not None
        assert other.poll() is None
    finally:
        for process in (mine, other):
            process.kill()
            process.wait(timeout=5)


def _is_pid_alive(pid: int) -> bool:
    """Return True when ``pid`` exists and is not a zombie."""
    parsed = InstanceService._read_proc_info(str(pid))
    return parsed is not None and parsed[3] != "Z"


def _spawn_setsid_instance(ignore_term: bool = False) -> tuple[subprocess.Popen, int]:
    """Spawn a launcher whose descendant moves into its own session via setsid."""
    trap_cmd = "trap '' TERM; " if ignore_term else ""
    inner = f"setsid bash -c '{trap_cmd}echo $$; exec sleep 30' & wait"
    process = subprocess.Popen(
        ["bash", "-c", inner],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        preexec_fn=os.setpgrp,
    )
    assert process.stdout is not None
    child_pid = int(process.stdout.readline().strip())
    return process, child_pid


@pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid is required")
def test_terminate_instance_stops_setsid_descendants_without_touching_others():
    """Stop must terminate SteamRT3-style setsid descendants even after the parent exits."""
    service = InstanceService.__new__(InstanceService)
    service.processes = {}
    service.pids = {}
    service.pgids = {}
    service.termination_in_progress = False

    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    launcher, setsid_child = _spawn_setsid_instance(ignore_term=False)
    try:
        assert os.getpgid(setsid_child) != launcher.pid
        service.processes[0] = launcher
        service.pids[0] = launcher.pid
        service.pgids[0] = launcher.pid

        service.terminate_instance(0)

        assert launcher.poll() is not None
        assert not _is_pid_alive(setsid_child)
        assert unrelated.poll() is None
        assert 0 not in service.processes
    finally:
        for pid in (setsid_child,):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for proc in (launcher, unrelated):
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid is required")
def test_terminate_all_escalates_to_sigkill_for_stubborn_setsid_descendants():
    """End session must SIGKILL setsid descendants that ignore SIGTERM after the launcher exits."""
    service = InstanceService.__new__(InstanceService)
    service._GRACEFUL_TERMINATION_TIMEOUT = 0.4
    service.processes = {}
    service.pids = {}
    service.pgids = {}
    service.termination_in_progress = False

    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    launcher, setsid_child = _spawn_setsid_instance(ignore_term=True)
    try:
        assert os.getpgid(setsid_child) != launcher.pid
        service.processes[0] = launcher
        service.pids[0] = launcher.pid
        service.pgids[0] = launcher.pid

        service.terminate_all()

        assert launcher.poll() is not None
        assert not _is_pid_alive(setsid_child)
        assert unrelated.poll() is None
        assert service.processes == {}
    finally:
        try:
            os.kill(setsid_child, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for proc in (launcher, unrelated):
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid is required")
def test_collect_instance_pids_strictly_isolates_target_tree():
    """Native PID collection returns only the target tree and nothing for unknown PGIDs."""
    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    launcher, setsid_child = _spawn_setsid_instance(ignore_term=False)
    try:
        assert InstanceService._collect_instance_pids(9999999) == {}

        collected = InstanceService._collect_instance_pids(launcher.pid)
        assert launcher.pid in collected
        assert setsid_child in collected
        assert unrelated.pid not in collected
        assert os.getpid() not in collected
        assert os.getppid() not in collected
    finally:
        try:
            os.kill(setsid_child, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for proc in (launcher, unrelated):
            proc.kill()
            proc.wait(timeout=5)


def test_unsafe_pgids_are_refused_in_native_and_flatpak_paths():
    """Unsafe PGIDs (<= 1 or own process group) must never signal any process."""
    service = InstanceService.__new__(InstanceService)
    own_pgid = os.getpgrp()

    for unsafe_pgid in (-5, 0, 1, own_pgid):
        assert InstanceService._collect_instance_pids(unsafe_pgid) == {}
        with (
            patch("src.services.instance.os.killpg") as mock_killpg,
            patch("src.services.instance.os.kill") as mock_kill,
        ):
            service._terminate_native_instance(0, Mock(), unsafe_pgid, {}, [])
            mock_killpg.assert_not_called()
            mock_kill.assert_not_called()

    for unsafe_pgid in (-5, 0, 1):
        with patch("src.services.instance.Utils.flatpak_spawn_host") as mock_spawn:
            service._terminate_flatpak_instance(0, Mock(), unsafe_pgid)
            mock_spawn.assert_not_called()

    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        for unsafe_pgid in (0, 1):
            script = InstanceService._build_flatpak_termination_script(unsafe_pgid, timeout=0.3)
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=5)
            assert result.returncode == 0
            assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


def test_flatpak_termination_script_never_matches_or_signals_unrelated_processes():
    """The Flatpak host script must return 0 PIDs for unknown PGIDs and never touch host processes."""
    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        script = InstanceService._build_flatpak_termination_script(9999999, timeout=0.3)
        # Verify the collector alone emits zero PIDs for a non-existent PGID
        # (guards against AWK associative-array auto-vivification bugs).
        probe = script.split("items=$(collect '');", 1)[0] + 'collect ""'
        probe_result = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, timeout=5)
        assert probe_result.returncode == 0
        assert probe_result.stdout.strip() == ""

        # Execute the full termination script and confirm the unrelated process survives.
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid is required")
def test_flatpak_termination_script_stops_setsid_descendants_without_touching_others():
    """The Flatpak host script must stop setsid descendants via SIGTERM without touching siblings."""
    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    launcher, setsid_child = _spawn_setsid_instance(ignore_term=False)
    try:
        assert os.getpgid(setsid_child) != launcher.pid
        script = InstanceService._build_flatpak_termination_script(launcher.pid, timeout=1.0)
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0

        launcher.wait(timeout=5)
        assert not _is_pid_alive(setsid_child)
        assert unrelated.poll() is None
    finally:
        try:
            os.kill(setsid_child, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for proc in (launcher, unrelated):
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid is required")
def test_flatpak_termination_script_escalates_to_sigkill_for_stubborn_setsid_descendants():
    """The Flatpak host script must SIGKILL stubborn setsid descendants without touching siblings."""
    unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
    launcher, setsid_child = _spawn_setsid_instance(ignore_term=True)
    try:
        assert os.getpgid(setsid_child) != launcher.pid
        script = InstanceService._build_flatpak_termination_script(launcher.pid, timeout=0.4)
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0

        launcher.wait(timeout=5)
        assert not _is_pid_alive(setsid_child)
        assert unrelated.poll() is None
    finally:
        try:
            os.kill(setsid_child, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for proc in (launcher, unrelated):
            proc.kill()
            proc.wait(timeout=5)


def _bwrap_available(*args: str) -> bool:
    """Return whether bwrap can create the requested sandbox namespaces."""
    if shutil.which("bwrap") is None:
        return False
    probe = subprocess.run(["bwrap", *args, "--", "true"], capture_output=True, timeout=10)
    return probe.returncode == 0


@pytest.mark.skipif(
    not Path("/bin/bash").exists() or not _bwrap_available("--dev-bind", "/", "/"),
    reason="bash and a working bwrap sandbox are needed for the host shell",
)
def test_the_host_shell_reports_the_process_group_of_the_instance():
    """The instance leads its own group, so it can be stopped as a whole."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()

    command = ["bwrap", "--dev-bind", "/", "/", "--", "sleep", "30"]
    escaped_command = " ".join(command)
    inner_script = f"echo $$; exec {escaped_command}"
    bash_path = shutil.which("bash")
    setsid_path = shutil.which("setsid")
    if not setsid_path:
        pytest.skip("setsid is needed to give the instance its own process group")

    leader = f"exec {setsid_path} -w {bash_path} -c {shlex.quote(inner_script)}"
    process = subprocess.Popen(
        ["bash", "-c", leader], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    reported = ""
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not reported:
            reported = process.stdout.readline().decode().strip()
            if not reported:
                time.sleep(0.1)

        assert reported.isdigit(), f"the host shell reported '{reported}'"

        groups = set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and reported not in groups:
            listing = subprocess.run(["ps", "-eo", "pid,pgid,cmd"], capture_output=True, text=True).stdout
            groups = {line.split()[1] for line in listing.splitlines() if "sleep 30" in line and "bwrap" not in line}
            if reported not in groups:
                time.sleep(0.1)
        assert reported in groups, "the reported group does not match the group of the instance"
    finally:
        cleanup_groups = {process.pid}
        if reported.isdigit():
            cleanup_groups.add(int(reported))
        for pgid in cleanup_groups:
            if pgid != os.getpgrp():
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.communicate(timeout=5)


@pytest.mark.skipif(
    not Path("/bin/bash").exists()
    or shutil.which("pasta") is None
    or not _bwrap_available("--unshare-user", "--unshare-net", "--ro-bind", "/", "/"),
    reason="bash, pasta and unprivileged bwrap namespaces are needed for the network setup",
)
def test_the_network_setup_lets_the_application_stop_itself(tmp_path):
    """Stopping an instance must not kill the application with SIGKILL."""
    log = tmp_path / "app.log"
    app = tmp_path / "app.sh"
    app.write_text("#!/bin/bash\n" f"trap 'echo TERM >> {log}; exit 0' TERM\n" f"echo started >> {log}\n" "sleep 30\n")
    app.chmod(0o755)

    environment = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path)}
    process = subprocess.Popen(
        [
            "bash",
            "-c",
            NETWORK_SETUP,
            "twinverse-network",
            "",
            "0",
            "bwrap",
            "--dev-bind",
            "/",
            "/",
            "--",
            str(app),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not log.exists():
            time.sleep(0.1)
        assert log.exists(), "the application did not start"

        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        time.sleep(2)

        assert "TERM" in log.read_text(), "the application was killed instead of asked to stop"
    finally:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
