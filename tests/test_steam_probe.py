"""Check that the Steam client of an instance is found, and only that one."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from src.core import Utils
from src.services.steam_probe import (
    STATUS_DOWN,
    STATUS_UP,
    SteamClientProbe,
    find_client_pids,
    is_update_progress,
)


def _fake_program(directory: Path, name: str) -> Path:
    """Build a program that answers to the given process name."""
    path = directory / name
    if not path.exists():
        interpreter = Path(sys.executable).resolve()
        path.write_text(
            f"#!{interpreter}\nimport sys, time\ntime.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 60)\n"
        )
        path.chmod(0o755)
    return path


def _fake_webhelper(directory: Path) -> Path:
    """Build a program that answers to the name of the Steam UI process."""
    return _fake_program(directory, "steamwebhelper")


def _spawn_client(directory: Path, name: str = "steamwebhelper") -> subprocess.Popen:
    """Start a program with the given process name in its own group."""
    return subprocess.Popen(
        [str(_fake_program(directory, name)), "60"],
        start_new_session=True,
    )


def _run_watcher(
    tmp_path: Path,
    monkeypatch,
    instance_num: int,
    launch_snippet: str = "",
) -> tuple[subprocess.Popen, Path]:
    """Run the real host watcher script in its own session, as launch does."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    probe = SteamClientProbe(instance_num)
    watcher = probe.watcher_script()
    script = f"{watcher} {launch_snippet} while true; do sleep 1; done"
    process = subprocess.Popen(["bash", "-c", script], start_new_session=True)
    return process, probe.status_path


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


def _stop_tree(process: subprocess.Popen) -> None:
    """Stop a test process group and any stray fake webhelper children."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except OSError:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def test_the_client_of_an_instance_is_found_by_the_group(tmp_path):
    """A steamwebhelper process in the group is the client of ours."""
    process = _spawn_client(tmp_path, "steamwebhelper")
    try:
        pids = find_client_pids(os.getpgid(process.pid))
        assert process.pid in pids
    finally:
        _stop_tree(process)


def test_the_bootstrapper_alone_is_not_taken_for_a_running_client(tmp_path):
    """The updater runs as 'steam' before the client opens and must not look ready."""
    process = _spawn_client(tmp_path, "steam")
    try:
        assert find_client_pids(os.getpgid(process.pid)) == []
    finally:
        _stop_tree(process)


def test_a_webhelper_in_a_descendant_session_is_found(tmp_path):
    """SteamRT3 starts pv-adverb and steamwebhelper with setsid; follow descendants."""
    webhelper = _fake_webhelper(tmp_path)
    child_pid_file = tmp_path / "child.pid"
    launcher = subprocess.Popen(
        [
            "bash",
            "-c",
            f"setsid {webhelper} 60 </dev/null >/dev/null 2>&1 & echo $! > {child_pid_file}; wait",
        ],
        start_new_session=True,
    )
    child_pid = None
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if child_pid_file.exists() and child_pid_file.read_text().strip().isdigit():
                child_pid = int(child_pid_file.read_text().strip())
                if find_client_pids(os.getpgid(launcher.pid)):
                    break
            time.sleep(0.1)
        assert child_pid is not None
        assert os.getpgid(child_pid) != os.getpgid(launcher.pid)
        assert child_pid in find_client_pids(os.getpgid(launcher.pid))
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except OSError:
                pass
        _stop_tree(launcher)


def test_a_process_of_another_group_is_never_taken(tmp_path):
    """The Steam of the user, or of another instance, is not our client."""
    process = _spawn_client(tmp_path, "steamwebhelper")
    try:
        other_group = os.getpgid(process.pid) + 100000
        assert find_client_pids(other_group) == []
    finally:
        _stop_tree(process)


def test_the_watcher_reports_the_client_that_came_up(tmp_path, monkeypatch):
    """The watcher detects steamwebhelper even inside a descendant session."""
    webhelper = _fake_webhelper(tmp_path)
    pid_file = tmp_path / "webhelper.pid"
    watcher, status = _run_watcher(
        tmp_path,
        monkeypatch,
        0,
        f"setsid {webhelper} 60 </dev/null >/dev/null 2>&1 & echo $! > {pid_file};",
    )
    try:
        assert _wait_for(status, STATUS_UP) == STATUS_UP
    finally:
        if pid_file.exists() and pid_file.read_text().strip().isdigit():
            try:
                os.kill(int(pid_file.read_text().strip()), signal.SIGKILL)
            except OSError:
                pass
        _stop_tree(watcher)


def test_the_watcher_ignores_the_steam_updater(tmp_path, monkeypatch):
    """While only the 'steam' updater runs, the watcher keeps reporting down."""
    updater = _fake_program(tmp_path, "steam")
    watcher, status = _run_watcher(tmp_path, monkeypatch, 1, f"{updater} 60 &")
    try:
        time.sleep(2.2)
        assert status.read_text().strip() == STATUS_DOWN
    finally:
        _stop_tree(watcher)


def test_the_watcher_reports_the_client_that_left(tmp_path, monkeypatch):
    """The watcher notices when steamwebhelper exits."""
    webhelper = _fake_webhelper(tmp_path)
    pid_file = tmp_path / "webhelper.pid"
    watcher, status = _run_watcher(
        tmp_path,
        monkeypatch,
        2,
        f"{webhelper} 60 & echo $! > {pid_file};",
    )
    try:
        assert _wait_for(status, STATUS_UP) == STATUS_UP
        os.kill(int(pid_file.read_text().strip()), signal.SIGKILL)
        assert _wait_for(status, STATUS_DOWN) == STATUS_DOWN
    finally:
        _stop_tree(watcher)


def test_the_watcher_does_not_take_itself_for_the_client(tmp_path, monkeypatch):
    """The command of the watcher mentions steamwebhelper, and must not match itself."""
    watcher, status = _run_watcher(tmp_path, monkeypatch, 3)
    try:
        time.sleep(2.2)
        assert status.read_text().strip() == STATUS_DOWN
    finally:
        _stop_tree(watcher)


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

    update = probe.read_updates(mark)

    assert update.progress == "Manifest download: waiting for download to finish"
    assert update.failure is None


def test_ipc_percent_lines_update_percent_without_overwriting_console_line(tmp_path, monkeypatch):
    """Steam prints 'Set percent complete: N' after every download status line."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    probe = SteamClientProbe(0)
    log = probe.client_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")

    with log.open("a", encoding="utf-8") as stream:
        stream.write("[2026-11-19 23:25:47] [2026-11-19 23:25:47] Downloading update (456,298 of 483,489 KB)...\n")
        stream.write(
            "[2026-11-19 23:25:47] [2026-11-19 23:25:47] "
            "Set status message: Downloading update (456,298 of 483,489 KB)...\n"
        )
        stream.write("[2026-11-19 23:25:47] [2026-11-19 23:25:47] Set percent complete: 94\n")

    update = probe.read_updates(0)

    assert update.progress == "Downloading update (456,298 of 483,489 KB)..."
    assert update.percent == 94
    assert is_update_progress(update.progress) is True


def test_the_lines_of_an_update_are_told_apart():
    """A client that updates itself says so, and a client that starts does not."""
    assert is_update_progress("Checking for available updates...") is True
    assert is_update_progress("Downloading update...") is True
    assert is_update_progress("Extracting package...") is True
    assert is_update_progress("Verifying installation...") is True
    assert is_update_progress("Cleaning up...") is True
    assert is_update_progress("Manifest download: waiting for download to finish") is True
    assert is_update_progress("Build: Mar  8 2026, at 12:00:00") is False


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

    update = probe.read_updates(mark)

    assert update.failure is None
    assert update.progress == "Manifest download: waiting for download to finish"


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

    update = probe.read_updates(mark)

    assert update.failure is not None
    assert "fatal IO error" in update.failure
    assert "some old line" not in update.failure
