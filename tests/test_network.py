"""Optional host dependency detection and launch argument preservation."""

import os
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from src.core import Utils
from src.services.instance import InstanceService
from src.services.network import network_command


@pytest.mark.parametrize("installed", [False, True])
def test_native_optional_network(monkeypatch, installed):
    """Preserve the original command when pasta is missing from the host."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    process = Mock(pid=123)
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    monkeypatch.setattr("src.services.instance.shutil.which", lambda name: name != "pasta" or installed)
    monkeypatch.setattr("subprocess.Popen", spawn)
    monkeypatch.setattr("time.sleep", lambda _: None)
    command = ["bwrap", "--dev-bind", "/", "/", "--", "printf", "%s", "spaces ' $ ;"]
    service._launch_natively(1, command, {})
    launched = spawn.call_args.args[0]
    if installed:
        assert launched[:2] == ["bash", "-c"]
        assert launched[4:] == command
    else:
        assert launched == command


@pytest.mark.parametrize("installed", [False, True])
def test_flatpak_detects_pasta_in_host_path(monkeypatch, tmp_path, installed):
    """Execute the generated host shell, including its actual dependency check."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    process = Mock(pid=123)
    process.poll.return_value = None
    process.stdout.readline.return_value = b"123\n"
    spawn = Mock(return_value=process)
    monkeypatch.setattr(Utils, "flatpak_spawn_host", spawn)
    monkeypatch.setattr("time.sleep", lambda _: None)
    value = "spaces ' $(not-a-command);"
    printf = shutil.which("printf")
    # Replace only network setup; the dependency check and quoting run for real.
    monkeypatch.setattr("src.services.instance.network_command", lambda _: [printf, "isolated:%s", value])
    service._launch_in_flatpak(1, [printf, "shared:%s", value], {})
    if installed:
        pasta = tmp_path / "pasta"
        pasta.write_text("#!/bin/sh\nexit 0\n")
        pasta.chmod(0o755)
    output = subprocess.check_output(
        spawn.call_args.args[0], executable="/bin/bash", env={**os.environ, "PATH": str(tmp_path)}, text=True
    )
    assert output.split("\n", 1)[1] == f"{'isolated' if installed else 'shared'}:{value}"
    spawn.assert_called_once()


def test_failed_helper_does_not_start_application_or_hang(tmp_path):
    """A failed pasta must terminate bwrap even while it blocks before exec."""
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    probe = subprocess.run(
        ["bwrap", "--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "--", "true"],
        capture_output=True,
        timeout=10,
    )
    if probe.returncode:
        pytest.skip("Unprivileged namespaces unavailable")
    pasta = tmp_path / "pasta"
    pasta.write_text("#!/bin/sh\nexit 42\n")
    pasta.chmod(0o755)
    command = network_command(["bwrap", "--ro-bind", "/", "/", "--die-with-parent", "--", "echo", "unexpected launch"])
    result = subprocess.run(
        command,
        env={**os.environ, "XDG_RUNTIME_DIR": str(tmp_path), "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 42, result.stderr
    assert not result.stdout
    assert not list(tmp_path.glob("twinverse-net.*"))
