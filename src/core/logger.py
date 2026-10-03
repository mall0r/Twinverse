"""Logger writing to both stderr and a log file."""

import logging
import sys
from pathlib import Path


class Logger:
    """
    Console and file output, without duplicating handlers.

    Attributes:
        log_dir (Path): The directory where log files are stored.
        logger (logging.Logger): The underlying standard Python logger instance.
    """

    def __init__(self, name: str, log_dir: Path, reset: bool = False, level: int = logging.INFO):
        """
        Create the log directory if missing and configure the named logger.

        Args:
            name: The name of the logger, typically `__name__` of the calling
                module.
            log_dir: Directory for the log file, created if missing.
            reset: Truncate the log file on startup instead of appending.
            level: Threshold for the logger, e.g. `logging.INFO`.
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self._handlers_setup = False
        self._setup_handlers(reset)

    def _setup_handlers(self, reset: bool):
        """
        Add the stderr and file handlers, at most once per logger.

        Args:
            reset: Truncate the log file instead of appending to it.
        """
        if self.logger.hasHandlers() or self._handlers_setup:
            return

        formatter = logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(console_handler)

        log_file = self.log_dir / f"{self.logger.name}.log"
        file_mode = "w" if reset else "a"
        file_handler = logging.FileHandler(log_file, mode=file_mode, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        self._handlers_setup = True

    def _should_log(self, level: int) -> bool:
        """
        Check if a given log level is enabled for the logger.

        Args:
            level: The level to test, e.g. `logging.INFO`.

        Returns:
            True if the level would be emitted, False otherwise.
        """
        return self.logger.isEnabledFor(level)

    def info(self, message: str):
        """
        Log an informational message.

        Args:
            message: Text to write to both handlers.
        """
        if self._should_log(logging.INFO):
            self.logger.info(message)

    def error(self, message: str):
        """
        Log an error message.

        Args:
            message: Text to write to both handlers.
        """
        if self._should_log(logging.ERROR):
            self.logger.error(message)

    def warning(self, message: str):
        """
        Log a warning message.

        Args:
            message: Text to write to both handlers.
        """
        if self._should_log(logging.WARNING):
            self.logger.warning(message)

    def debug(self, message: str):
        """
        Log a debug message.

        Args:
            message: Text to write to both handlers.
        """
        if self._should_log(logging.DEBUG):
            self.logger.debug(message)

    def exception(self, message: str):
        """
        Log an exception with traceback.

        Args:
            message: Context for the traceback that follows it.
        """
        if self._should_log(logging.ERROR):
            self.logger.exception(message)

    def flush(self):
        """Flush all handlers, so buffered records reach their destination."""
        for handler in self.logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()
