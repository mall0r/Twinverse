#!/usr/bin/env python3
"""
Main module for the Twinverse application.

This module serves as the entry point for the Twinverse application,
launching the GUI interface.
"""

from src import TwinverseApplication


def main():
    """Run the Twinverse GUI application."""
    TwinverseApplication.run_gui()


if __name__ == "__main__":
    main()
