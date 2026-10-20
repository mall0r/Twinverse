"""Shared test isolation for XDG state and logging."""

import os

import pytest

from src.core.logging import reset_logging


@pytest.fixture(autouse=True)
def isolated_xdg(monkeypatch, tmp_path):
    """Keep tests away from the real XDG directories and developer logging."""
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(variable, str(tmp_path / variable.lower()))
    for variable in list(os.environ):
        if variable.startswith("TWINVERSE_"):
            monkeypatch.delenv(variable, raising=False)
    reset_logging()
    yield
    reset_logging()
