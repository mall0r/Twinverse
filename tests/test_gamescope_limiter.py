"""Verify the live Gamescope limiter is passed to Proton without losing arguments."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.models import Profile
from src.services.cmd_builder import CommandBuilder

PROBE = """
import json, os, sys
print(json.dumps({
    'ro': os.environ.get('PRESSURE_VESSEL_FILESYSTEMS_RO'),
    'rw': os.environ.get('PRESSURE_VESSEL_FILESYSTEMS_RW'),
    'limiter': os.environ.get('GAMESCOPE_LIMITER_FILE'),
    'args': sys.argv[1:],
}))
"""


@pytest.mark.parametrize("existing", [None, "", "/existing one:/existing-two"])
def test_limiter_is_resolved_after_gamescope_starts(tmp_path, monkeypatch, existing):
    """Execute the generated child wrapper with a newly created instance path."""
    builder = CommandBuilder(Mock(), Profile(), {}, Mock(), 0, tmp_path, None)
    limiter = str(tmp_path / "limiter with spaces ' $value ;")
    monkeypatch.setattr(builder, "_build_bwrap_command", lambda _: ["env"])
    # Simulate Gamescope generating a new path only when it starts its child.
    monkeypatch.setattr(
        builder,
        "_build_gamescope_command",
        lambda _: [
            "sh",
            "-c",
            'export GAMESCOPE_LIMITER_FILE="$1"; shift; shift; exec "$@"',
            "fake-gamescope",
            limiter,
        ],
    )
    env = os.environ.copy()
    env["GAMESCOPE_LIMITER_FILE"] = "/stale-parent-path"
    env["PRESSURE_VESSEL_FILESYSTEMS_RW"] = "/existing-writable"
    if existing is None:
        env.pop("PRESSURE_VESSEL_FILESYSTEMS_RO", None)
    else:
        env["PRESSURE_VESSEL_FILESYSTEMS_RO"] = existing
    args = ["argument with spaces", "$(exit 99)", "'quoted'", ""]
    command = builder.build_command([sys.executable, "-c", PROBE, *args])
    result = json.loads(subprocess.check_output(command, env=env, text=True))
    assert result == {
        "ro": f"{existing}:{limiter}" if existing else limiter,
        "rw": "/existing-writable",
        "limiter": limiter,
        "args": args,
    }


def test_missing_limiter_preserves_runtime_settings():
    """Gamescope versions without a limiter file still launch the child normally."""
    env = os.environ.copy()
    env.pop("GAMESCOPE_LIMITER_FILE", None)
    env["PRESSURE_VESSEL_FILESYSTEMS_RO"] = "/existing"
    result = json.loads(
        subprocess.check_output(
            ["sh", "-c", CommandBuilder.GAMESCOPE_RUNTIME_SETUP, "twinverse-gamescope", sys.executable, "-c", PROBE],
            env=env,
            text=True,
        )
    )
    assert result["ro"] == "/existing"


def test_no_gamescope_does_not_modify_runtime_settings(tmp_path, monkeypatch):
    """Plain Steam and terminal launches keep their original environment."""
    builder = CommandBuilder(Mock(), Profile(use_gamescope=False), {}, Mock(), 0, Path(tmp_path), None)
    monkeypatch.setattr(builder, "_build_bwrap_command", lambda _: ["env"])
    env = os.environ.copy()
    env["GAMESCOPE_LIMITER_FILE"] = "/parent-path"
    env["PRESSURE_VESSEL_FILESYSTEMS_RO"] = "/existing"
    result = json.loads(
        subprocess.check_output(builder.build_command([sys.executable, "-c", PROBE]), env=env, text=True)
    )
    assert result["ro"] == "/existing"
