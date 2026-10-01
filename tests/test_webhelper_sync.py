"""Exercise the UI startup gate against real process file descriptors."""

import os
import subprocess
from contextlib import ExitStack

import pytest

from src.core import Config
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


def test_other_bash_scripts_skip_gate_and_keep_existing_hook(tmp_path):
    """Run inherited Bash initialization without delaying unrelated scripts."""
    gate = tmp_path / "gate.sh"
    gate.write_text(WEBHELPER_GATE)
    inherited = tmp_path / "inherited.sh"
    inherited.write_text("export TWINVERSE_TEST_VALUE=preserved\n")
    script = tmp_path / "steam.sh"
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


def test_missing_webhelper_skips_overlay(monkeypatch, tmp_path):
    """Allow first-time Steam setup before its UI launcher has been downloaded."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(Config, "CACHE_DIR", cache)

    assert build_webhelper_mounts(tmp_path / "new-instance", 0) == []
    assert not cache.exists()
