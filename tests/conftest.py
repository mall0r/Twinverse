"""Shared test isolation for XDG state and logging."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.i18n import LANGUAGE_EN, set_language
from src.core.logging import reset_logging


@pytest.fixture(autouse=True)
def isolated_xdg(monkeypatch, tmp_path):
    """Keep tests away from the real XDG directories and developer logging."""
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(variable, str(tmp_path / variable.lower()))
    for variable in list(os.environ):
        if variable.startswith("TWINVERSE_"):
            monkeypatch.delenv(variable, raising=False)
    set_language(LANGUAGE_EN)
    reset_logging()
    yield
    set_language(LANGUAGE_EN)
    reset_logging()


@pytest.fixture(scope="session")
def node_executable():
    """Return a runnable Node.js binary, skipping if none works."""
    candidates = [str(Path(sys.executable).parent / "node"), shutil.which("node")]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen or not os.path.isfile(candidate):
            continue
        seen.add(candidate)
        try:
            probe = subprocess.run([candidate, "--version"], capture_output=True, timeout=5)
        except OSError:
            continue
        if probe.returncode == 0:
            return candidate
    pytest.skip("A runnable Node.js runtime is required to execute KWin scripts")
