"""Exercise the UI startup gate against real process file descriptors."""

import os
import subprocess
import time
from contextlib import ExitStack
from unittest.mock import Mock, patch

import pytest

from src.core import Config, Utils
from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder
from src.services.webhelper_sync import WEBHELPER_GATE, build_webhelper_mounts


@pytest.mark.parametrize("state", ["ready", "stale", "unopened", "missing_pid"])
def test_gate_checks_current_client_handles_and_preserves_launcher(tmp_path, state):
    """Require current handles, bound failed waits, and preserve launcher arguments."""
    original = tmp_path / "steamwebhelper.sh"
    original.write_text('printf "%s\\n" "$0" "$@"\n')
    wrapper = tmp_path / "gate.sh"
    wrapper.write_text(
        WEBHELPER_GATE.replace("/dev/shm", str(tmp_path)).replace(
            "SECONDS - tv_started < 20", "SECONDS - tv_started < 1"
        )
    )
    with ExitStack() as stack:
        for name in ("c9edbd50", "fe20b6d7", "671c2a99"):
            path = tmp_path / f"u{os.getuid()}-Shm_{name}"
            path.write_text("old")
            if state in ("ready", "stale"):
                stack.enter_context(path.open())
            if state == "stale":
                path.unlink()
                path.write_text("replacement")

        args = [f"-steampid={os.getpid()}", "argument with spaces; $(false)"]
        if state == "missing_pid":
            args = args[1:]
        result = subprocess.run(
            ["bash", str(original), *args],
            env={**os.environ, "BASH_ENV": str(wrapper)},
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

    assert result.stdout.splitlines() == [str(original), *args]
    if state == "ready":
        assert "shared memory ready" in result.stderr
    else:
        assert "starting UI normally" in result.stderr


def test_webhelper_hook_preserves_steam_script(monkeypatch, tmp_path):
    """Keep managed Steam files outside the mounts so verification and updates work."""
    monkeypatch.setattr(Config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.delenv("BASH_ENV", raising=False)
    home = tmp_path / "instance"
    original = home / ".local/share/Steam/ubuntu12_64/steamwebhelper.sh"
    original.parent.mkdir(parents=True)
    original.write_text("#!/bin/bash\necho original\n")

    mounts = build_webhelper_mounts(home, 1)

    cache = tmp_path / "cache/steam-webhelper/instance_2"
    assert mounts == [
        "--ro-bind",
        str(cache),
        "/tmp/twinverse-webhelper",
        "--setenv",
        "BASH_ENV",
        "/tmp/twinverse-webhelper/gate.sh",
    ]
    assert original.read_text() == "#!/bin/bash\necho original\n"
    assert os.access(cache / "gate.sh", os.X_OK)

    original.write_text("#!/bin/bash\necho updated\n")
    build_webhelper_mounts(home, 1)
    assert original.read_text() == "#!/bin/bash\necho updated\n"


def test_overlay_focus_repair_only_in_splitscreen(tmp_path):
    """Limit the focus repair to splitscreen instances running Gamescope."""
    devices = Mock()
    devices.get_instance_dimensions.return_value = (1280, 720)

    for splitscreen, gamescope, expected in [(True, True, True), (False, True, False), (True, False, False)]:
        profile = Profile(
            use_gamescope=gamescope,
            mode="splitscreen" if splitscreen else "multi_monitor",
            player_configs=[PlayerInstanceConfig()],
        )
        builder = CommandBuilder(Mock(), profile, {}, devices, 0, tmp_path / "home", None)
        with patch("src.services.cmd_builder.build_webhelper_mounts", return_value=[]) as mounts:
            builder.build_command()

        assert mounts.call_args.kwargs["fix_overlay_focus"] is expected


def test_other_bash_scripts_skip_gate_and_keep_existing_hook(tmp_path):
    """Run inherited Bash initialization without delaying unrelated scripts."""
    gate = tmp_path / "gate.sh"
    gate.write_text(WEBHELPER_GATE)
    inherited = tmp_path / "inherited.sh"
    inherited.write_text("export TWINVERSE_TEST_VALUE=preserved\n")
    script = tmp_path / "unrelated.sh"
    script.write_text('printf "%s" "$TWINVERSE_TEST_VALUE"\n')
    result = subprocess.run(
        ["bash", str(script), f"-steampid={os.getpid()}"],
        env={**os.environ, "BASH_ENV": str(gate), "TWINVERSE_ORIGINAL_BASH_ENV": str(inherited)},
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    assert result.stdout == "preserved"
    assert "Twinverse:" not in result.stderr


def _stderr_of(tmp_path, name, gate, *args):
    """Return what the gate writes to stderr while the named script runs."""
    script = tmp_path / name
    script.write_text("#!/bin/bash\nexit 0\n")
    result = subprocess.run(
        ["bash", str(script), *args],
        env={**os.environ, "BASH_ENV": str(gate)},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stderr


def _run_gate(tmp_path, name, gate, *args):
    """Run a named script through the generated gate with a stubbed Python."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "python3"
    stub.write_text('#!/bin/bash\nprintf "%s\\n" "$2" >> "$TWINVERSE_TEST_CALLS"\n')
    stub.chmod(0o755)

    script = tmp_path / name
    script.write_text("#!/bin/bash\nexit 0\n")

    calls = tmp_path / "calls.log"
    calls.unlink(missing_ok=True)
    subprocess.run(
        ["bash", str(script), *args],
        env={
            **os.environ,
            "BASH_ENV": str(gate),
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
            "TWINVERSE_TEST_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    # The repair is started in the background, so wait for the stub to record it.
    deadline = time.monotonic() + 5
    while not calls.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return calls.read_text().splitlines() if calls.exists() else []


def _sandbox_gate(tmp_path, monkeypatch):
    """Generate the real gate with its helper paths inside the test sandbox."""
    monkeypatch.setattr(Config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(Config, "LOG_DIR", tmp_path / "cache/logs")
    home = tmp_path / "instance"
    (home / ".local/share/Steam/ubuntu12_64").mkdir(parents=True)
    (home / ".local/share/Steam/ubuntu12_64/steamwebhelper.sh").write_text("#!/bin/bash\n")
    build_webhelper_mounts(home, 0, fix_overlay_focus=True)
    gate_path = tmp_path / "cache/steam-webhelper/instance_1/gate.sh"
    gate_path.write_text(
        gate_path.read_text()
        .replace("/tmp/twinverse-webhelper", str(gate_path.parent))
        .replace("/tmp/twinverse-logs", str(tmp_path / "cache/logs"))
        .replace("SECONDS - tv_started < 20", "SECONDS - tv_started < 1")
    )
    return gate_path


@pytest.mark.parametrize("script", ["steamwebhelper.sh", "steam.sh"])
def test_overlay_repair_starts_in_every_client_layout(tmp_path, monkeypatch, script):
    """Reach the repair from both launchers, since SteamRT3 skips its own wrapper."""
    gate_path = _sandbox_gate(tmp_path, monkeypatch)
    calls = _run_gate(tmp_path, script, gate_path, f"-steampid={os.getpid()}")
    assert len(calls) == 1 and calls[0].isdigit()


def test_only_steams_ui_launcher_waits_for_controller_memory(tmp_path, monkeypatch):
    """Keep the shared-memory wait on the webhelper, never on the launcher."""
    gate_path = _sandbox_gate(tmp_path, monkeypatch)
    assert "starting UI normally" in _stderr_of(tmp_path, "steamwebhelper.sh", gate_path)
    assert _stderr_of(tmp_path, "steam.sh", gate_path) == ""


def test_unrelated_scripts_never_start_the_overlay_repair(tmp_path, monkeypatch):
    """Keep the launcher hook narrow so game scripts stay untouched."""
    gate_path = _sandbox_gate(tmp_path, monkeypatch)
    assert _run_gate(tmp_path, "unrelated.sh", gate_path) == []


def test_missing_webhelper_skips_overlay(monkeypatch, tmp_path):
    """Allow first-time Steam setup before its UI launcher has been downloaded."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(Config, "CACHE_DIR", cache)

    assert build_webhelper_mounts(tmp_path / "new-instance", 0) == []
    assert not cache.exists()


def test_overlay_focus_hook_only_installed_on_request(monkeypatch, tmp_path):
    """Start the focus repair only for requested instances and keep it standalone."""
    logs = tmp_path / "cache/twinverse/logs"
    monkeypatch.setattr(Config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(Config, "LOG_DIR", logs)
    home = tmp_path / "instance"
    launcher = home / ".local/share/Steam/ubuntu12_64/steamwebhelper.sh"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/bash\necho original\n")
    cache = tmp_path / "cache/steam-webhelper/instance_1"

    assert "/tmp/twinverse-logs" not in build_webhelper_mounts(home, 0)
    assert "overlay_focus" not in (cache / "gate.sh").read_text()
    assert not (cache / "overlay_focus.py").exists()

    mounts = build_webhelper_mounts(home, 0, fix_overlay_focus=True)
    gate = (cache / "gate.sh").read_text()
    assert "overlay_focus.py" in gate
    helper = Utils.get_base_path() / "res/steam/overlay_focus.py"
    assert (cache / "overlay_focus.py").read_text() == helper.read_text()
    assert launcher.read_text() == "#!/bin/bash\necho original\n"

    # The instance home shadows the real one, so the shared log directory has
    # to be mounted explicitly for the repair to reach it.
    bind_at = mounts.index("--bind", 1)
    assert mounts[bind_at + 1 : bind_at + 3] == [str(logs), "/tmp/twinverse-logs"]
    assert logs.is_dir()

    # Other scripts must not launch the repair, so the early return stays first.
    without_ui = tmp_path / "fresh-instance"
    build_webhelper_mounts(without_ui, 1, fix_overlay_focus=True)
    fresh_gate = (tmp_path / "cache/steam-webhelper/instance_2/gate.sh").read_text()
    assert fresh_gate.index("*) return 0 ;;") < fresh_gate.index("overlay_focus.py")


def test_overlay_focus_log_lands_in_the_shared_log_directory(monkeypatch, tmp_path):
    """Keep every Twinverse log together instead of inside the instance home."""
    logs = tmp_path / "cache/twinverse/logs"
    monkeypatch.setattr(Config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(Config, "LOG_DIR", logs)
    home = tmp_path / "instance"
    (home / ".local/share/Steam/ubuntu12_64").mkdir(parents=True)
    (home / ".local/share/Steam/ubuntu12_64/steamwebhelper.sh").write_text("#!/bin/bash\n")

    build_webhelper_mounts(home, 1, fix_overlay_focus=True)
    gate = (tmp_path / "cache/steam-webhelper/instance_2/gate.sh").read_text()

    # Same instance number as the cache directory, so the pair is unambiguous.
    assert "/tmp/twinverse-logs/overlay_focus_instance_2.log" in gate
    assert "$HOME" not in gate
    assert ".local/share/twinverse" not in gate
