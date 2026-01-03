import os
import sys
import subprocess
import shlex
from pathlib import Path
from typing import List, Dict


class Utils:

    @staticmethod
    def get_base_path() -> Path:
        """
        Gets the base path for the application, handling PyInstaller.

        - When running as a script, it returns the project root.
        - When running as a PyInstaller bundle, it returns the path to the extracted files.
        """
        if getattr(sys, "frozen", False):
            # Running in a PyInstaller bundle
            return Path(sys._MEIPASS)
        else:
            # Running as a script, assuming this file is in src/core
            return Path(__file__).resolve().parent.parent.parent


    @staticmethod
    def is_flatpak() -> bool:
        """Checks if the application is running inside a Flatpak."""
        return os.path.exists("/.flatpak-info")

    @staticmethod
    def run_host_command(command: List[str], **kwargs) -> subprocess.CompletedProcess:
        """
        Executes a command on the host system using 'flatpak-spawn --host'.
        """
        base_command = ["flatpak-spawn", "--host"]
        full_command = base_command + command
        return subprocess.run(full_command, **kwargs)

    @staticmethod
    def run_host_command_async(command: List[str], **kwargs) -> subprocess.Popen:
        """
        Executes a command asynchronously on the host system using 'flatpak-spawn --host'.

        Returns:
            subprocess.Popen: The Popen object for the spawned process.
        """
        base_command = ["flatpak-spawn", "--host"]
        full_command = base_command + command
        return subprocess.Popen(full_command, **kwargs)

    @staticmethod
    def set_host_env_vars(env_vars: Dict[str, str]) -> None:
        """
        Sets environment variables on the host system when running in a Flatpak.
        """
        if not Utils.is_flatpak():
            return

        command_parts = []
        for key, value in env_vars.items():
            command_parts.append(f"export {key}={shlex.quote(value)}")

        command_string = "; ".join(command_parts)

        # We don't need to capture output or check for errors here.
        Utils.run_host_command(['sh', '-c', command_string], check=False)
