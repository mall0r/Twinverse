"""Custom exceptions raised by the application."""


class TwinverseError(Exception):
    """Base exception for all custom errors raised by the application."""

    pass


class ProfileNotFoundError(TwinverseError):
    """Raised when a specified game profile `.json` file cannot be found."""

    pass


class DependencyError(TwinverseError):
    """Raised when a required external dependency (e.g., `steam`, `gamescope`) is not found on the system's PATH."""

    pass


class VirtualDeviceError(TwinverseError):
    """Raised when there is an error creating or managing a virtual device."""

    pass
