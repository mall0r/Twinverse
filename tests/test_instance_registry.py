"""Check that the instances outliving a session are found and can be stopped."""

import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

from src.core.utils import Utils
from src.services.instance import InstanceService
from src.services.instance_registry import (
    NATIVE,
    InstanceProbe,
    InstanceRecord,
    InstanceRegistry,
    RecoveredInstance,
    belongs_to_instance,
    read_host_cmdline,
)
from src.services.steam_probe import SteamClientProbe


def _spawn_with_marker(marker: str) -> subprocess.Popen:
    """Start a process whose command line carries the given marker."""
    return subprocess.Popen(
        ["bash", "-c", f"exec -a {shlex.quote(marker)} sleep 30"],
        start_new_session=True,
    )


def _service(registry: InstanceRegistry, probe: InstanceProbe) -> InstanceService:
    """Build an instance service that only knows the registry."""
    service = InstanceService.__new__(InstanceService)
    service._registry = registry
    service._probe = probe
    service.processes = {}
    service.pids = {}
    service.pgids = {}
    service.recovered_instances = []
    return service


def test_the_registry_keeps_the_launched_instances(tmp_path):
    """The registry stores the instances and forgets them one by one."""
    registry = InstanceRegistry(tmp_path / "instances.json")
    registry.add(InstanceRecord(instance=0, pgid=11, mode=NATIVE, home="/home/1", log="/logs/1.log"))
    registry.add(InstanceRecord(instance=1, pgid=12, mode=NATIVE, home="/home/2", log="/logs/2.log"))

    records = registry.load()
    assert [record.instance for record in records] == [0, 1]
    assert records[0].pgid == 11

    registry.remove(0)
    assert [record.instance for record in registry.load()] == [1]

    registry.save([])
    assert not registry.path.exists()


def test_a_damaged_registry_is_ignored(tmp_path):
    """A file that cannot be read must not stop the application."""
    registry = InstanceRegistry(tmp_path / "instances.json")
    registry.path.write_text("{not json")

    assert registry.load() == []


def test_a_recycled_process_is_never_taken_for_an_instance():
    """A process group that belongs to something else must be left alone."""
    record = InstanceRecord(instance=0, pgid=4242, mode=NATIVE, home="/home/twinverse/home_1", log="/logs/one.log")

    assert belongs_to_instance(record, "/usr/bin/some-other-program --flag") is False
    assert belongs_to_instance(record, "") is False
    assert belongs_to_instance(record, "bwrap --bind /home/twinverse/home_1 /home/user") is True
    assert belongs_to_instance(record, "bash -c exec steam >> /logs/one.log 2>&1") is True


def test_an_instance_of_a_previous_session_is_found_and_stopped(tmp_path):
    """The instance that outlived the session is registered and can be stopped."""
    home = tmp_path / "home_1"
    process = _spawn_with_marker(str(home))
    registry = InstanceRegistry(tmp_path / "instances.json")
    registry.add(InstanceRecord(instance=0, pgid=process.pid, mode=NATIVE, home=str(home)))
    service = _service(registry, InstanceProbe(ttl=0.0))

    recovered = service._recover_instances()

    assert len(recovered) == 1
    assert recovered[0].instance == 0
    assert 0 in service.processes
    assert isinstance(service.processes[0], RecoveredInstance)
    assert service.processes[0].poll() is None

    service.terminate_instance(0)

    assert process.poll() is not None
    assert registry.load() == []


def test_an_instance_that_is_gone_is_forgotten(tmp_path):
    """A record of an instance that no longer runs must be dropped."""
    home = tmp_path / "home_1"
    registry = InstanceRegistry(tmp_path / "instances.json")
    registry.add(InstanceRecord(instance=0, pgid=999999, mode=NATIVE, home=str(home)))
    service = _service(registry, InstanceProbe(ttl=0.0))

    recovered = service._recover_instances()

    assert recovered == []
    assert service.processes == {}
    assert registry.load() == []


def test_a_process_of_another_program_is_not_taken_over(tmp_path):
    """A process group that was recycled by the system must be ignored."""
    home = tmp_path / "home_1"
    other = _spawn_with_marker(str(tmp_path / "something-else"))
    registry = InstanceRegistry(tmp_path / "instances.json")
    registry.add(InstanceRecord(instance=0, pgid=other.pid, mode=NATIVE, home=str(home)))
    service = _service(registry, InstanceProbe(ttl=0.0))

    try:
        recovered = service._recover_instances()
    finally:
        other.kill()
        other.wait(timeout=10)

    assert recovered == []
    assert service.processes == {}


def test_the_registry_file_is_private(tmp_path):
    """The registry holds the paths of the user and must not be readable by others."""
    registry = InstanceRegistry(tmp_path / "instances.json")
    registry.add(InstanceRecord(instance=0, pgid=11, mode=NATIVE, home="/home/1"))

    assert os.stat(registry.path).st_mode & 0o077 == 0
    assert Path(registry.path).read_text().strip().startswith("{")


def test_the_log_of_the_client_is_only_read_once(tmp_path, monkeypatch):
    """A long update does not make every check read the whole log again."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    service = InstanceService.__new__(InstanceService)
    service._client_log_offsets = {}

    probe = SteamClientProbe(0)
    log = probe.client_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("old\n")

    update = service.client_status(0)
    assert (update.progress, update.failure) == (None, None)

    with log.open("a", encoding="utf-8") as stream:
        stream.write("[2026-10-20] Manifest download: waiting for download to finish\n")

    update = service.client_status(0)
    assert update.progress == "Manifest download: waiting for download to finish"
    assert update.failure is None

    # The same lines are not read again.
    update = service.client_status(0)
    assert (update.progress, update.failure) == (None, None)


def test_the_percentage_of_the_update_is_kept(tmp_path, monkeypatch):
    """A step without a percentage does not make the bar lose the progress."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    service = InstanceService.__new__(InstanceService)
    service._client_log_offsets = {}

    probe = SteamClientProbe(0)
    log = probe.client_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("old\n")
    service.client_status(0)

    with log.open("a", encoding="utf-8") as stream:
        stream.write("[ 41%] Downloading update...\n")

    assert service.client_status(0).percent == 41

    with log.open("a", encoding="utf-8") as stream:
        stream.write("[----] Installing update...\n")

    update = service.client_status(0)
    assert update.progress == "Installing update..."
    assert update.percent == 41


def test_the_registry_lives_in_the_state_directory(monkeypatch, tmp_path):
    """The registry follows the XDG state directory, like the logs."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    registry = InstanceRegistry()

    assert registry.path == tmp_path / "state/twinverse/instances.json"


def test_the_host_command_line_is_read_through_the_flatpak_helper(monkeypatch):
    """Inside a Flatpak the command line of the host needs the helper."""
    monkeypatch.setattr(Utils, "is_flatpak", lambda: True)
    monkeypatch.setattr(
        Utils,
        "flatpak_spawn_host",
        lambda command, **kwargs: SimpleNamespace(
            stdout="bash -c exec steam >> /logs/one.log 2>&1\n",
            returncode=0,
        ),
    )
    record = InstanceRecord(instance=0, pgid=42, mode="flatpak", home="/x", log="/logs/one.log")

    cmdline = read_host_cmdline(42)

    assert "/logs/one.log" in cmdline
    assert belongs_to_instance(record, cmdline) is True
