"""Global configuration settings and XDG paths used throughout the application."""

import os
import sys
import tempfile
import warnings
from pathlib import Path

from .utils import Utils

APP_NAME = "twinverse"
APP_ID = "io.github.mall0r.Twinverse"


def ensure_private_dir(path: Path) -> Path:
    """Create a directory tree with owner-only permissions and return the leaf."""
    path = Path(path).expanduser()
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent

    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise

    try:
        path.chmod(0o700)
    except OSError:
        # The application may not own an XDG directory created by the user.
        pass
    return path


def _is_flatpak() -> bool:
    """Check for Flatpak without requiring a GUI or the application package."""
    try:
        return Utils.is_flatpak()
    except Exception:  # pragma: no cover - defensive fallback
        return Path("/.flatpak-info").exists()


def _flatpak_app_dir() -> Path:
    """Return the per-application directory Flatpak exposes to the host."""
    app_id = os.environ.get("FLATPAK_ID") or APP_ID
    return Path.home() / ".var" / "app" / app_id


def _xdg_dir(variable: str, fallback: str, flatpak_fallback: str) -> Path:
    """
    Resolve an XDG base directory and append the application name.

    Absolute values from the environment always win. A relative value is
    ignored, as required by the XDG Base Directory Specification. Flatpak
    exports absolute XDG variables, so the direct app path is only used on
    older Flatpak releases that do not.
    """
    value = os.environ.get(variable)
    if value:
        path = Path(value)
        if path.is_absolute():
            return path / APP_NAME
        warnings.warn(
            f"{variable} must be an absolute path; ignoring {value!r}.",
            RuntimeWarning,
            stacklevel=3,
        )

    if _is_flatpak():
        return _flatpak_app_dir() / flatpak_fallback / APP_NAME
    return Path.home() / fallback / APP_NAME


class Config:
    """Global Twinverse configurations."""

    APP_NAME = APP_NAME
    APP_ID = APP_ID

    @staticmethod
    def _get_script_dir() -> Path:
        frozen = getattr(sys, "frozen", False)
        meipass = getattr(sys, "_MEIPASS", None)
        if frozen and meipass:
            return Path(meipass)
        return Path(__file__).parent.parent.parent

    SCRIPT_DIR: Path = _get_script_dir()
    APP_DIR: Path = Path(__file__).parent.parent.parent

    @staticmethod
    def data_dir() -> Path:
        """Return ``$XDG_DATA_HOME/twinverse``."""
        return _xdg_dir("XDG_DATA_HOME", ".local/share", "data")

    @staticmethod
    def config_dir() -> Path:
        """Return ``$XDG_CONFIG_HOME/twinverse``."""
        return _xdg_dir("XDG_CONFIG_HOME", ".config", "config")

    @staticmethod
    def cache_dir() -> Path:
        """Return ``$XDG_CACHE_HOME/twinverse`` for disposable files."""
        return _xdg_dir("XDG_CACHE_HOME", ".cache", "cache")

    @staticmethod
    def state_dir() -> Path:
        """Return ``$XDG_STATE_HOME/twinverse`` for persistent application state."""
        return _xdg_dir("XDG_STATE_HOME", ".local/state", ".local/state")

    @staticmethod
    def logs_dir() -> Path:
        """Return the developer log directory inside the XDG state directory."""
        return Config.state_dir() / "logs"

    @staticmethod
    def runtime_dir() -> Path:
        """Return a per-user runtime directory for ephemeral fallback files."""
        value = os.environ.get("XDG_RUNTIME_DIR")
        if value:
            runtime = Path(value)
            if runtime.is_absolute():
                return runtime / Config.APP_NAME
        return Path(tempfile.gettempdir()) / f"{Config.APP_NAME}-{os.getuid()}"

    @staticmethod
    def get_profile_path() -> Path:
        """Return the path to the default profile JSON file."""
        return Config.config_dir() / "profile.json"

    @staticmethod
    def get_steam_home_path(instance_num: int) -> Path:
        """Return the isolated Steam home path for a given instance."""
        return Config.data_dir() / f"home_{instance_num + 1}"
