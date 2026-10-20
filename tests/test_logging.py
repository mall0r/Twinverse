"""Exercise XDG paths, logging setup, redaction and diagnostics."""

import json
import logging
import os
import time
from pathlib import Path

import pytest

from src.core import Config, Utils
from src.core.logging import (
    InstanceLog,
    LogPaths,
    LogSettings,
    configure_logging,
    log_context,
)
from src.core.logging.diagnostics import collect_diagnostics, format_diagnostics
from src.core.logging.retention import prune_logs


def test_xdg_paths_follow_the_environment(monkeypatch, tmp_path):
    """Every base directory is resolved lazily and includes the app name."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    assert Config.data_dir() == tmp_path / "data/twinverse"
    assert Config.config_dir() == tmp_path / "config/twinverse"
    assert Config.cache_dir() == tmp_path / "cache/twinverse"
    assert Config.state_dir() == tmp_path / "state/twinverse"
    assert Config.logs_dir() == tmp_path / "state/twinverse/logs"


def test_flatpak_fallback_uses_the_direct_app_state_directory(monkeypatch, tmp_path):
    """Older Flatpak releases expose no XDG variables, so use the app home."""
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(Utils, "is_flatpak", lambda: True)
    monkeypatch.setenv("FLATPAK_ID", "io.github.mall0r.Twinverse")

    base = tmp_path / "home/.var/app/io.github.mall0r.Twinverse"
    assert Config.data_dir() == base / "data/twinverse"
    assert Config.config_dir() == base / "config/twinverse"
    assert Config.cache_dir() == base / "cache/twinverse"
    assert Config.logs_dir() == base / ".local/state/twinverse/logs"


def test_relative_xdg_paths_are_ignored(monkeypatch, tmp_path):
    """The XDG specification requires absolute values."""
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    with pytest.warns(RuntimeWarning):
        assert Config.state_dir() == tmp_path / "home/.local/state/twinverse"


def test_settings_environment_and_cli_override():
    """The CLI wins over the environment while keeping unknown GTK flags."""
    environ = {
        "TWINVERSE_DEBUG": "1",
        "TWINVERSE_LOG_FORMAT": "json",
        "TWINVERSE_LOG_MAX_BYTES": "4096",
    }
    settings = LogSettings.from_environment(environ)
    assert settings.debug is True
    assert settings.console_level == logging.DEBUG
    assert settings.format.value == "json"
    assert settings.max_bytes == 64 * 1024  # clamped to a safe minimum

    parsed, remaining = LogSettings.from_argv(["--quiet", "--log-level", "error"], "1.0")
    assert parsed.console_level == logging.ERROR
    assert parsed.quiet is True
    assert remaining == []

    parsed, remaining = LogSettings.from_argv(["--diagnostics", "--json", "--gtk-flag"], "1.0")
    assert parsed.diagnostics is True
    assert parsed.diagnostics_json is True
    assert remaining == ["--gtk-flag"]


def test_configure_writes_a_contextual_and_redacted_log(tmp_path):
    """Records carry run and instance context, and secrets are masked."""
    settings = LogSettings(log_dir=tmp_path, console=False)
    handle = configure_logging(settings)
    logger = logging.getLogger("src.test")
    with log_context(instance=2):
        logger.warning("password=%s token=abc123", "hunter2")

    handle.shutdown()
    text = (tmp_path / "twinverse.log").read_text()
    assert f"run_id={handle.run_id}" in text
    assert "instance=2" in text
    assert "password=***" in text
    assert "token=***" in text
    assert "hunter2" not in text
    assert "abc123" not in text


def test_json_format_is_one_object_per_line(tmp_path):
    """JSON logs remain machine-readable after redaction."""
    settings = LogSettings(log_dir=tmp_path, console=False, format="json")
    handle = configure_logging(settings)
    logging.getLogger("src.test").warning("PASSWORD=secret-value")
    handle.shutdown()

    lines = [line for line in (tmp_path / "twinverse.log").read_text().splitlines() if line]
    payload = next(item for item in map(json.loads, lines) if item["message"] == "PASSWORD=***")
    assert payload["run_id"] == handle.run_id
    assert payload["level"] == "WARNING"


def test_instance_log_redacts_the_command_and_retains_a_limit(tmp_path):
    """Per-launch logs keep secrets out and are pruned per instance."""
    settings = LogSettings(log_dir=tmp_path, console=False)
    handle = configure_logging(settings)
    instance_log = InstanceLog.create(
        0,
        command=["steam", "--password", "hunter2"],
        env_keys=["PASSWORD", "DISPLAY"],
        base_dir=tmp_path,
    )
    assert instance_log.path is not None
    instance_log.write(b"child output\n")
    instance_log.finish(exit_code=0)
    text = instance_log.path.read_text()
    assert "--password ***" in text
    assert "hunter2" not in text
    assert "environment keys: DISPLAY, PASSWORD" in text
    assert "child output" in text

    paths = LogPaths.resolve(tmp_path)
    now = time.time()
    for index in range(4):
        old = paths.instances / f"instance-01-2020010{index}-deadbeef.log"
        old.write_text("old")
        os.utime(old, (now - index, now - index))
    removed = prune_logs(paths, keep_instances=2, max_age_days=14)
    assert removed == 3
    assert len(list(paths.instances.glob("instance-01-*.log"))) == 2
    handle.shutdown()


def test_diagnostics_are_available_before_gtk(tmp_path):
    """Diagnostics describe the environment and the active log directory."""
    settings = LogSettings(log_dir=tmp_path, console=False)
    handle = configure_logging(settings)
    logging.getLogger("src.test").info("diagnostic marker")
    data = collect_diagnostics(handle)

    assert data["application"]["name"] == "Twinverse"
    assert data["logging"]["directory"] == str(tmp_path)
    assert data["application"]["run_id"] == handle.run_id
    assert "recent log" in format_diagnostics(data)
    assert "diagnostic marker" in data["recent_log"]
    handle.shutdown()
