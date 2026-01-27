"""
Twinverse application source package.

This package provides core functionalities, GUI components, data models,
and various services for managing Steam instances.
"""

from .core import (
    Config,
    DependencyError,
    Logger,
    ProfileNotFoundError,
    TwinverseError,
    VirtualDeviceError,
)
from .gui.app import TwinverseApplication
from .gui.windows import MainWindow, PreferencesWindow
from .models import Profile, SteamInstance
from .services import DeviceManager, InstanceService, KdeManager

__all__ = [
    "Config",
    "DependencyError",
    "Logger",
    "TwinverseError",
    "ProfileNotFoundError",
    "VirtualDeviceError",
    "TwinverseApplication",
    "MainWindow",
    "PreferencesWindow",
    "Profile",
    "SteamInstance",
    "DeviceManager",
    "InstanceService",
    "KdeManager",
]
