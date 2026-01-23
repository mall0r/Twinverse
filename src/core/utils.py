"""
Utility module for the Twinverse application.

This module provides utility functions and classes that are commonly used
throughout the Twinverse application.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Literal, Union, overload


class Utils:
    """Provides utility functions for the Twinverse application."""

    @staticmethod
    def get_base_path() -> Path:
        """
        Get the base path for the application, handling PyInstaller.

        - When running as a script, it returns the project root.
        - When running as a PyInstaller bundle, it returns the path to the extracted files.
        """
        if getattr(sys, "frozen", False):
            # Running in a PyInstaller bundle
            return Path(sys._MEIPASS)  # type: ignore[attr-defined]
        else:
            # Running as a script, assuming this file is in src/core
            return Path(__file__).resolve().parent.parent.parent

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
            command (List[str]): The command to execute.
            async_ (bool): If True, execute asynchronously and return a Popen object.
                           Otherwise, run synchronously and return a CompletedProcess object.
            **kwargs: Additional arguments to pass to subprocess.run or subprocess.Popen.

        Returns:
            Union[subprocess.CompletedProcess, subprocess.Popen]: The result of the command execution.
        """
        if Utils.is_flatpak():
            command = ["flatpak-spawn", "--host"] + command

        if async_:
            return subprocess.Popen(command, **kwargs)
        else:
            return subprocess.run(command, **kwargs)
