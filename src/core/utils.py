"""Utilities shared across the application."""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Literal, Union, overload


class Utils:
    """Path, version and host-spawn helpers."""

    @staticmethod
    def get_base_path() -> Path:
        """
        Get the base path for the application, handling PyInstaller.

        - When running as a script, it returns the project root.
        - When running as a PyInstaller bundle, it returns the path to the extracted files.
        """
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS)  # type: ignore[attr-defined]
        else:
            return Path(__file__).resolve().parent.parent.parent

    @staticmethod
    def get_version() -> str:
        """Get application version."""
        try:
            version_file = Utils.get_base_path() / "version"
            with open(version_file, "r") as f:
                return f.read().strip()
        except Exception:
            return "Unknown"

    @staticmethod
    def is_wayland() -> bool:
        """Check if the application is running on Wayland."""
        return os.environ.get("XDG_SESSION_TYPE") == "wayland"

    @staticmethod
    def is_flatpak() -> bool:
        """Check if the application is running inside a Flatpak."""
        return os.path.exists("/.flatpak-info")

    @overload
    @staticmethod
    def flatpak_spawn_host(command: List[str], async_: Literal[True], **kwargs) -> subprocess.Popen: ...

    @overload
    @staticmethod
    def flatpak_spawn_host(
        command: List[str], async_: Literal[False] = False, **kwargs
    ) -> subprocess.CompletedProcess: ...

    @staticmethod
    def flatpak_spawn_host(
        command: List[str], async_: bool = False, **kwargs
    ) -> Union[subprocess.CompletedProcess, subprocess.Popen]:
        """
        Execute a command, using 'flatpak-spawn --host' if inside a Flatpak.

        Args:
            command: The command and its arguments.
            async_: Start the command without waiting for it.
            **kwargs: Passed through to subprocess.run or subprocess.Popen.

        Returns:
            A Popen when async_ is True, a CompletedProcess otherwise.
        """
        if Utils.is_flatpak():
            command = ["flatpak-spawn", "--host"] + command

        if async_:
            return subprocess.Popen(command, **kwargs)
        else:
            return subprocess.run(command, **kwargs)
