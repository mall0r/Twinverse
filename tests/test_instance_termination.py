"""Stop the instances without touching the other ones or the host."""

import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.services.instance import InstanceService
from src.services.network import NETWORK_SETUP


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
