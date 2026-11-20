"""Optional host dependency detection and launch argument preservation."""

import os
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from src.core import Config, Utils
from src.models import PlayerInstanceConfig, Profile
from src.services.instance import InstanceService
from src.services.network import GUEST_ADDRESS_SETUP, NETWORK_SETUP, network_command


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
        assert launched[4:6] == ["", "1"]
        assert launched[6:] == command
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
    monkeypatch.setattr(Config, "logs_dir", lambda: tmp_path / "logs")
    value = "spaces ' $(not-a-command);"
    printf = shutil.which("printf")
    # Replace only network setup; the dependency check and quoting run for real.
    monkeypatch.setattr("src.services.instance.network_command", lambda *args: [printf, "isolated:%s", value])
    service._launch_in_flatpak(1, [printf, "shared:%s", value], {})
    if installed:
        pasta = tmp_path / "pasta"
        pasta.write_text("#!/bin/sh\nexit 0\n")
        pasta.chmod(0o755)
    subprocess.check_output(
        spawn.call_args.args[0], executable="/bin/bash", env={**os.environ, "PATH": str(tmp_path)}, text=True
    )
    # The instance writes to its own log file instead of the pipe of the launcher.
    log = next((tmp_path / "logs" / "instances").glob("instance-02-*.log")).read_text()
    body = log.split("\n\n", 1)[1] if "\n\n" in log else ""
    assert body.strip() == f"{'isolated' if installed else 'shared'}:{value}"
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


def test_network_command_keeps_the_address_and_the_command():
    """The guest address and the instance index travel before the bwrap call."""
    command = ["bwrap", "--ro-bind", "/", "/", "--", "printf", "%s", "a b"]
    wrapped = network_command(command, "192.168.18.60/24", 2)
    assert wrapped[:4] == ["bash", "-c", NETWORK_SETUP, "twinverse-network"]
    assert wrapped[4:6] == ["192.168.18.60/24", "2"]
    assert wrapped[6:] == command


def test_the_setup_does_not_disable_ipv6():
    """IPv6 stays available inside the guest; only the IPv4 address changes."""
    assert "--ipv4-only" not in NETWORK_SETUP


def _write_selection_tools(tmp_path, address="192.168.18.52", prefix="24", used=()):
    """Create the host tools and the ARP table used by the shell selection."""
    ip = tmp_path / "ip"
    ip.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  "-4 route show default") echo "default via 192.168.18.1 dev ens4 proto dhcp src '
        f'{address} metric 100" ;;\n'
        f'  "-4 -o addr show dev ens4 scope global") echo "2: ens4    inet {address}/{prefix} '
        'brd 192.168.18.255 scope global dynamic ens4" ;;\n'
        f'  "-4 -o addr show scope global") echo "2: ens4    inet {address}/{prefix} '
        'brd 192.168.18.255 scope global dynamic ens4" ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n"
    )
    ip.chmod(0o755)

    ping = tmp_path / "ping"
    ping.write_text("#!/bin/sh\nexit 1\n")
    ping.chmod(0o755)

    arp = tmp_path / "arp"
    lines = ["IP address       HW type     Flags       HW address            Mask     Device"]
    for entry in used:
        lines.append(f"{entry}   0x1         0x2         aa:bb:cc:dd:ee:ff     *        ens4")
    arp.write_text("\n".join(lines) + "\n")
    return arp


def _select_guest_address(tmp_path, arp, index):
    """Run the host selection as the network setup does."""
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "TWINVERSE_ARP_FILE": str(arp),
    }
    return subprocess.run(
        ["bash", "-c", GUEST_ADDRESS_SETUP + '\nselect_guest_address "$1"', "twinverse-address", str(index)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def test_the_guest_address_avoids_the_host_and_used_addresses(tmp_path):
    """A free address at the top of the subnet is selected for each instance."""
    arp = _write_selection_tools(tmp_path, used=("192.168.18.253",))
    result = _select_guest_address(tmp_path, arp, 0)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "192.168.18.252/24"

    result = _select_guest_address(tmp_path, arp, 1)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "192.168.18.249/24"


def test_the_guest_address_is_not_the_host_address(tmp_path):
    """The host address itself is never handed to a guest."""
    arp = _write_selection_tools(tmp_path, address="192.168.18.253", used=())
    result = _select_guest_address(tmp_path, arp, 0)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != "192.168.18.253/24"


def test_the_guest_address_needs_an_ipv4_subnet(tmp_path):
    """Without a host IPv4 address the setup keeps the shared network."""
    ip = tmp_path / "ip"
    ip.write_text("#!/bin/sh\nexit 1\n")
    ip.chmod(0o755)
    arp = tmp_path / "arp"
    arp.write_text("IP address       HW type     Flags       HW address            Mask     Device\n")
    result = _select_guest_address(tmp_path, arp, 0)
    assert result.returncode != 0
    assert not result.stdout.strip()


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


def test_network_setup_passes_the_selected_address_to_pasta(tmp_path):
    """The selected IPv4 address reaches pasta together with the bwrap call."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    arp = _write_selection_tools(tmp_path, used=("192.168.18.253",))
    args_file = tmp_path / "pasta-args"
    _write_recording_pasta(tmp_path, args_file)

    command = network_command(["bwrap", "--ro-bind", "/", "/", "--", "true"])
    result = subprocess.run(
        command,
        env={
            **os.environ,
            "XDG_RUNTIME_DIR": str(tmp_path),
            "TWINVERSE_ARP_FILE": str(arp),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    args = args_file.read_text().splitlines()
    assert "-a" in args
    assert "192.168.18.252/24" in args
    assert not list(tmp_path.glob("twinverse-net.*"))


def test_network_setup_keeps_the_shared_network_without_ipv4(tmp_path):
    """Without a host IPv4 address pasta starts without the guest address."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    ip = tmp_path / "ip"
    ip.write_text("#!/bin/sh\nexit 1\n")
    ip.chmod(0o755)
    args_file = tmp_path / "pasta-args"
    _write_recording_pasta(tmp_path, args_file)

    command = network_command(["bwrap", "--ro-bind", "/", "/", "--", "true"])
    result = subprocess.run(
        command,
        env={
            **os.environ,
            "XDG_RUNTIME_DIR": str(tmp_path),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "no free guest address" in result.stderr
    assert "-a" not in args_file.read_text().splitlines()


@pytest.mark.parametrize("value", [None, "", "   ", "not-an-address", "999.1.1.1", "2001:db8::1"])
def test_an_invalid_guest_address_falls_back_to_the_automatic_choice(value):
    """A typo must not prevent the instance from starting."""
    profile = Profile(PLAYERS=[PlayerInstanceConfig(GUEST_IP=value), PlayerInstanceConfig()])
    assert InstanceService._configured_guest_address(profile, 0) is None


@pytest.mark.parametrize("value", ["192.168.18.60", "192.168.18.60/24"])
def test_a_valid_guest_address_is_kept(value):
    """A configured address is handed to the host setup unchanged."""
    profile = Profile(PLAYERS=[PlayerInstanceConfig(GUEST_IP=value), PlayerInstanceConfig()])
    assert InstanceService._configured_guest_address(profile, 0) == value


def _run_with_resolv_conf(tmp_path, resolv_conf, application):
    """Run the network setup with a stand-in for /etc/resolv.conf."""
    ip = tmp_path / "ip"
    ip.write_text("#!/bin/sh\nexit 1\n")
    ip.chmod(0o755)
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
    """Bubblewrap cannot mount over a symlink, so the file it points to is replaced."""
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
    """The SELinux policy denies pasta the /proc/PID/ns directory, so the setup stops it instead."""
    if not _unprivileged_namespaces_available():
        pytest.skip("Unprivileged namespaces unavailable")
    resolv_conf = tmp_path / "resolv.conf"
    resolv_conf.write_text("nameserver 192.0.2.1\n")
    result = _run_with_resolv_conf(tmp_path, resolv_conf, ["true"])
    assert result.returncode == 0, result.stderr
    assert "--no-netns-quit" in (tmp_path / "pasta-args").read_text().splitlines()
