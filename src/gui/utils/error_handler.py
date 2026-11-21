"""Centralized error formatting and handling."""

from typing import Callable

from src.core.exceptions import DependencyError, TwinverseError, VirtualDeviceError
from src.core.i18n import t


class ErrorHandler:
    """Maps exception types to user-facing messages."""

    _ERROR_FORMATTERS: dict[type, Callable[[Exception], str]] = {
        DependencyError: lambda e: t("error.missing_dependency", error=e),
        VirtualDeviceError: lambda e: t("error.virtual_device", error=e),
        TwinverseError: lambda e: t("error.twinverse", error=e),
    }

    @classmethod
    def format_error(cls, error: Exception) -> str:
        """
        Format an error for display to the user.

        Args:
            error: The exception to format.

        Returns:
            A message safe to show in a dialog, never a traceback.
        """
        for error_type, formatter in cls._ERROR_FORMATTERS.items():
            if isinstance(error, error_type):
                return formatter(error)

        if isinstance(error, FileNotFoundError):
            filename = getattr(error, "filename", None)
            if filename:
                return t("error.command_not_found", filename=filename)
            return t("error.file_not_found", error=error)

        if isinstance(error, OSError):
            if hasattr(error, "errno") and error.errno == 2:
                filename = getattr(error, "filename", None)
                if filename:
                    return t("error.command_not_found", filename=filename)
                return t("error.file_not_found", error=error)
            return t("error.system", error=error)

        return t("error.launch_failed", error=error)

    @classmethod
    def register_formatter(cls, error_type: type, formatter: Callable[[Exception], str]):
        """
        Register a custom error formatter, taking precedence over the defaults.

        Args:
            error_type: The exception type to format.
            formatter: Turns an exception into the message to display.
        """
        cls._ERROR_FORMATTERS[error_type] = formatter
