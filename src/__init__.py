"""
MultiScope application source package.

This package provides core functionalities, GUI components, data models,
and various services for managing Steam instances.
"""

from .core import (
    Config,
    DependencyError,
    Logger,
    MultiScopeError,
    ProfileNotFoundError,
    VirtualDeviceError,
)
from .gui.app import MultiScopeApplication, MultiScopeWindow, run_gui
from .models import Profile, SteamInstance
from .services import DeviceManager, InstanceService, KdeManager

__all__ = [
    "Config",
    "DependencyError",
    "Logger",
    "MultiScopeError",
    "ProfileNotFoundError",
    "VirtualDeviceError",
    "MultiScopeApplication",
    "MultiScopeWindow",
    "run_gui",
    "Profile",
    "SteamInstance",
    "DeviceManager",
    "InstanceService",
    "KdeManager",
]