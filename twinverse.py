#!/usr/bin/env python3
"""Entry point for the Twinverse application, launching the GUI interface."""

import logging
import os
import sys
from typing import Optional, Sequence

from src.core.logging import LogSettings, configure_logging
from src.core.logging.diagnostics import collect_diagnostics, print_diagnostics
from src.core.utils import Utils


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Configure logging, handle CLI-only modes, then start the GUI."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    settings, gui_arguments = LogSettings.from_argv(arguments, Utils.get_version())
    handle = configure_logging(settings)
    logger = logging.getLogger("src.entrypoint")

    logger.info("Twinverse %s starting (run=%s, pid=%d)", Utils.get_version(), handle.run_id, os.getpid())
    logger.debug(
        "Base path=%s; python=%s; logs=%s",
        Utils.get_base_path(),
        sys.version.split()[0],
        handle.paths.root if handle.paths else "disabled",
    )

    try:
        if settings.diagnostics:
            data = collect_diagnostics(handle)
            print_diagnostics(data, as_json=settings.diagnostics_json)
            return 0

        # Import GTK only after logging and diagnostics are ready. This keeps
        # ``--diagnostics`` useful on a broken GTK installation.
        from src.gui.app import TwinverseApplication

        return TwinverseApplication.run_gui(gui_arguments)
    except KeyboardInterrupt:
        logger.warning("Interrupted by the user")
        return 130
    except Exception:
        logger.critical("Fatal error", exc_info=True)
        return 1
    finally:
        logger.info("Twinverse stopped")
        handle.shutdown()


if __name__ == "__main__":
    sys.exit(main())
