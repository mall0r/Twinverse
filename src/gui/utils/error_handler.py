"""
Error handler utility module.

This module provides centralized error formatting and handling.
"""

from typing import Callable

from src.core.exceptions import DependencyError, TwinverseError, VirtualDeviceError


class ErrorHandler:
    """Centralized error formatting and handling."""

    _ERROR_FORMATTERS: dict[type, Callable[[Exception], str]] = {
        DependencyError: lambda e: f"Missing dependency: {e}",
        VirtualDeviceError: lambda e: f"Virtual device error: {e}",
        TwinverseError: lambda e: f"Twinverse error: {e}",
    }

    @classmethod
    def format_error(cls, error: Exception) -> str:
        """
        Format an error for display to the user.

        Args:
            error: The exception to format

        Returns:
            Formatted error message
        """
        # Try specific error types
        for error_type, formatter in cls._ERROR_FORMATTERS.items():
            if isinstance(error, error_type):
                return formatter(error)

        # Handle FileNotFoundError
        if isinstance(error, FileNotFoundError):
            filename = getattr(error, "filename", None)
            if filename:
                return f"Required command '{filename}' not found. Please install the missing dependency."
            return f"Required file or command not found: {error}"

        # Handle OSError (errno 2 = ENOENT)
        if isinstance(error, OSError):
            if hasattr(error, "errno") and error.errno == 2:
                filename = getattr(error, "filename", None)
                if filename:
                    return f"Required command '{filename}' not found. Please install the missing dependency."
                return f"Required file or command not found: {error}"
            return f"System error: {error}"

        # Default
        return f"Could not launch: {error}"

    @classmethod
    def register_formatter(cls, error_type: type, formatter: Callable[[Exception], str]):
        """
        Register a custom error formatter.

        Args:
            error_type: The exception type to format
            formatter: Function that takes an exception and returns a string
        """
        cls._ERROR_FORMATTERS[error_type] = formatter
