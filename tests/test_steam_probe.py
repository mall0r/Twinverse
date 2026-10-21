"""Check that the Steam client of an instance is found, and only that one."""

import os
import subprocess
import time
from pathlib import Path

from src.core import Utils
from src.services.steam_probe import (
    STATUS_DOWN,
    STATUS_UP,
    SteamClientProbe,
    find_client_pids,
)


def _fake_steam(directory: Path) -> Path:
    """Build a program that answers to the name of the Steam client."""
    path = directory / "steam"
    path.symlink_to("/bin/sleep")
    return path


def _spawn_client(directory: Path) -> subprocess.Popen:
    """Start a program named like the Steam client, in its own group."""
    return subprocess.Popen(
        [str(_fake_steam(directory)), "60"],
        start_new_session=True,
    )


def _run_watcher(status_path: Path, client: Path | None = None) -> subprocess.Popen:
    """
    Run the watcher of the host, the same way the launch command does.

    The watcher and the client share the process group of the launch, which
    is what tells the client of an instance apart from the Steam of the user.
    """
    start = f"{client} 60 & " if client is not None else ""
    script = (
        f"status={status_path}; "
        "( state=; "
        "while kill -0 $$ 2>/dev/null; do "
        "if pgrep -g $$ -x 'steam|steamclient64' >/dev/null 2>&1; then current=up; else current=down; fi; "
        f'[ "$state" = "$current" ] || {{ echo $current > $status; state=$current; }}; '
        "sleep 1; done ) >/dev/null 2>&1 & "
        f"{start}"
        "while true; do sleep 1; done"
    )
    return subprocess.Popen(["bash", "-c", script], start_new_session=True)


def _wait_for(path: Path, expected: str, timeout: float = 8.0) -> str:
    """Wait until the watcher writes the expected state."""
    deadline = time.time() + timeout
    value = ""
    while time.time() < deadline:
        try:
            value = path.read_text().strip()
        except OSError:
            value = ""
        if value == expected:
            return value
        time.sleep(0.2)
    return value


def _kill_clients() -> None:
    """Stop every program that answers to the name of the Steam client."""
    subprocess.run(["pkill", "-x", "steam"], capture_output=True)
    subprocess.run(["pkill", "-x", "steamclient64"], capture_output=True)


def test_the_client_of_an_instance_is_found_by_the_group(tmp_path):
    """A process of the group, named like the client, is the client of ours."""
    process = _spawn_client(tmp_path)
    try:
        pids = find_client_pids(os.getpgid(process.pid))
        assert process.pid in pids
    finally:
        process.kill()
        process.wait(timeout=10)


def test_a_process_of_another_group_is_never_taken(tmp_path):
    """The Steam of the user, or of another instance, is not our client."""
    process = _spawn_client(tmp_path)
    try:
        other_group = os.getpgid(process.pid) + 100000
        assert find_client_pids(other_group) == []
    finally:
        process.kill()
        process.wait(timeout=10)


def test_the_watcher_reports_the_client_that_came_up(tmp_path):
    """The watcher on the host tells the application that the client is up."""
    status = tmp_path / "instance-01.status"
    watcher = _run_watcher(status, _fake_steam(tmp_path))
    try:
        assert _wait_for(status, STATUS_UP) == STATUS_UP
    finally:
        watcher.kill()
        _kill_clients()
        watcher.wait(timeout=10)


def test_the_watcher_reports_the_client_that_left(tmp_path):
    """The watcher notices that the client is gone."""
    status = tmp_path / "instance-02.status"
    watcher = _run_watcher(status, _fake_steam(tmp_path))
    try:
        assert _wait_for(status, STATUS_UP) == STATUS_UP
        _kill_clients()
        assert _wait_for(status, STATUS_DOWN) == STATUS_DOWN
    finally:
        watcher.kill()
        _kill_clients()
        watcher.wait(timeout=10)


def test_the_watcher_does_not_take_itself_for_the_client(tmp_path):
    """The command of the watcher mentions Steam, and must not match itself."""
    status = tmp_path / "instance-03.status"
    watcher = _run_watcher(status)
    try:
        time.sleep(2.5)
        assert status.read_text().strip() == STATUS_DOWN
    finally:
        watcher.kill()
        watcher.wait(timeout=10)


def test_the_probe_reads_the_state_of_the_host(tmp_path, monkeypatch):
    """Inside a Flatpak the state comes from the file of the watcher."""
    monkeypatch.setattr(Utils, "is_flatpak", lambda: True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    probe = SteamClientProbe(0)

    assert probe.is_client_up(12345) is False

    probe.status_path.parent.mkdir(parents=True, exist_ok=True)
    probe.status_path.write_text("up\n")

    assert probe.is_client_up(12345) is True


def test_the_progress_comes_from_the_log_of_the_client(tmp_path, monkeypatch):
    """The last useful line of the Steam log tells what it is doing."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    probe = SteamClientProbe(0)
    log = probe.client_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("old line\n")
    mark = probe.client_log_size()

    with log.open("a", encoding="utf-8") as stream:
        stream.write("[2026-10-20] ERROR: ld.so: object x cannot be loaded\n")
        stream.write("[2026-10-20] Manifest download: waiting for download to finish\n")

    progress, failure = probe.read_updates(mark)

    assert progress == "Manifest download: waiting for download to finish"
    assert failure is None


def test_a_line_that_only_looks_like_a_failure_is_not_a_failure(tmp_path, monkeypatch):
    """A Steam that updates itself writes lines that must not stop it."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    probe = SteamClientProbe(0)
    log = probe.client_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("old\n")
    mark = probe.client_log_size()

    with log.open("a", encoding="utf-8") as stream:
        stream.write("[2026-10-20] Failed to open the update window, continuing\n")
        stream.write("[2026-10-20] Manifest download: waiting for download to finish\n")

    progress, failure = probe.read_updates(mark)

    assert failure is None
    assert progress == "Manifest download: waiting for download to finish"


def test_the_failure_reason_comes_from_the_log_of_the_client(tmp_path, monkeypatch):
    """The fatal line of the Steam client is the reason the user reads."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    probe = SteamClientProbe(0)
    log = probe.client_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("some old line\n")
    mark = probe.client_log_size()

    with log.open("a", encoding="utf-8") as stream:
        stream.write('[2026-10-20] XIO:  fatal IO error 110 (Connection timed out) on X server ":0"\n')

    progress, failure = probe.read_updates(mark)

    assert failure is not None
    assert "fatal IO error" in failure
    assert "some old line" not in failure
