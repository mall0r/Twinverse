"""Stop the instances without touching the other ones or the host."""

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.gui.controllers.launch_controller import LaunchController
from src.services.instance import InstanceService
from src.services.network import NETWORK_SETUP


def _controller(terminate=None):
    """Build a launch controller with a mocked instance service."""
    service = Mock()
    if terminate is not None:
        service.terminate_all.side_effect = terminate
    controller = LaunchController(service, Mock(), Mock())
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


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="bash is needed for the network setup")
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
    try:
        deadline = time.monotonic() + 10
        reported = ""
        while time.monotonic() < deadline and not reported:
            reported = process.stdout.readline().decode().strip()
            if not reported:
                time.sleep(0.1)

        assert reported.isdigit(), f"the host shell reported '{reported}'"

        listing = subprocess.run(["ps", "-eo", "pid,pgid,cmd"], capture_output=True, text=True).stdout
        groups = {line.split()[1] for line in listing.splitlines() if "sleep 30" in line and "bwrap" not in line}
        assert reported in groups, "the reported group does not match the group of the instance"
    finally:
        process.kill()
        process.wait(timeout=5)


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="bash is needed for the network setup")
def test_the_network_setup_lets_the_application_stop_itself(tmp_path):
    """Stopping an instance must not kill the application with SIGKILL."""
    log = tmp_path / "app.log"
    app = tmp_path / "app.sh"
    app.write_text("#!/bin/bash\n" f"trap 'echo TERM >> {log}; exit 0' TERM\n" f"echo started >> {log}\n" "sleep 30\n")
    app.chmod(0o755)

    environment = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path)}
    process = subprocess.Popen(
        ["bash", "-c", NETWORK_SETUP, "twinverse-network", "bwrap", "--dev-bind", "/", "/", "--", str(app)],
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
