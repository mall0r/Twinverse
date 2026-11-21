"""Optional host dependency detection and launch argument preservation."""

import os
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from src.core import Utils
from src.services.instance import InstanceService
from src.services.network import network_command


def _unprivileged_namespaces_available() -> bool:
    """Return whether bwrap can create the namespaces used by the setup."""
    if not shutil.which("bwrap"):
        return False
    probe = subprocess.run(
        ["bwrap", "--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "--", "true"],
        capture_output=True,
        timeout=10,
    )
    return probe.returncode == 0


def _write_recording_pasta(tmp_path, args_file):
    """Create a pasta that records its arguments and stays alive like the real one."""
    pasta = tmp_path / "pasta"
    pasta.write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$@" > "{args_file}"\n'
        "pidfile=\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        "    --pid) pidfile=$2; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        'echo $$ > "$pidfile"\n'
        "exec sleep 30\n"
    )
    pasta.chmod(0o755)
    return pasta


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
    if not _unprivileged_namespaces_available():
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


def _run_with_resolv_conf(tmp_path, resolv_conf, application):
    """Run the network setup with a stand-in for /etc/resolv.conf."""
    _write_recording_pasta(tmp_path, tmp_path / "pasta-args")
    command = network_command(["bwrap", "--ro-bind", "/", "/", "--", *application])
    return subprocess.run(
        command,
        env={
            **os.environ,
            "XDG_RUNTIME_DIR": str(tmp_path),
            "TWINVERSE_RESOLV_CONF": str(resolv_conf),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_network_setup_replaces_a_regular_resolv_conf(tmp_path):
    """A plain resolv.conf is replaced inside the sandbox and left alone on the host."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.write_text("nameserver 192.0.2.1\n")
    result = _run_with_resolv_conf(tmp_path, resolv_conf, ["cat", str(resolv_conf)])
    assert result.returncode == 0, result.stderr
    assert result.stdout == "nameserver 169.254.1.1\n"
    assert resolv_conf.read_text() == "nameserver 192.0.2.1\n"


def test_network_setup_follows_a_symlinked_resolv_conf(tmp_path):
    """Replace the symlink target because bwrap cannot mount over a link."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    (tmp_path / "etc").mkdir()
    (tmp_path / "run").mkdir()
    stub = tmp_path / "run" / "stub-resolv.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    resolv_conf = tmp_path / "etc" / "resolv.conf"
    # The same relative link that systemd-resolved installs.
    resolv_conf.symlink_to("../run/stub-resolv.conf")
    result = _run_with_resolv_conf(tmp_path, resolv_conf, ["cat", str(resolv_conf)])
    assert result.returncode == 0, result.stderr
    assert "symlink" not in result.stderr
    assert result.stdout == "nameserver 169.254.1.1\n"
    assert stub.read_text() == "nameserver 127.0.0.53\n"
    assert resolv_conf.is_symlink()


def test_network_setup_starts_with_a_dangling_resolv_conf(tmp_path):
    """A link to a missing file keeps the host DNS instead of failing the launch."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.symlink_to(tmp_path / "missing" / "resolv.conf")
    result = _run_with_resolv_conf(tmp_path, resolv_conf, ["echo", "started"])
    assert result.returncode == 0, result.stderr
    assert result.stdout == "started\n"
    assert "points to a missing file" in result.stderr


def test_pasta_does_not_watch_the_namespace_directory(tmp_path):
    """Ensure pasta disables netns directory watching under enforcing SELinux."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.write_text("nameserver 192.0.2.1\n")
    result = _run_with_resolv_conf(tmp_path, resolv_conf, ["true"])
    assert result.returncode == 0, result.stderr
    assert "--no-netns-quit" in (tmp_path / "pasta-args").read_text().splitlines()
