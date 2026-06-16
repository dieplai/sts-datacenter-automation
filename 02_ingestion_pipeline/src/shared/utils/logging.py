"""Centralized logging module for the Data Ingestion System."""

import logging
import sys
from datetime import datetime
from pathlib import Path


class CustomFormatter(logging.Formatter):
    """Custom formatter for logging with date_time:file_name:line : Message format."""

    FORMAT = "%(asctime)s: %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self):
        super().__init__(self.FORMAT, self.DATE_FORMAT)

    def format(self, record):
        """Format the log record."""
        return super().format(record)


# Create logger instance
_logger = logging.getLogger("sts_data_ingestion")

# Prevent duplicate handlers
if not _logger.handlers:
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(CustomFormatter())
    _logger.addHandler(console_handler)

    # Set logger level
    _logger.setLevel(logging.DEBUG)


def info(message: str) -> None:
    """Log info level message."""
    _logger.info(message)


def debug(message: str) -> None:
    """Log debug level message."""
    _logger.debug(message)


def warning(message: str) -> None:
    """Log warning level message."""
    _logger.warning(message)


def error(message: str) -> None:
    """Log error level message."""
    _logger.error(message)


def critical(message: str) -> None:
    """Log critical level message."""
    _logger.critical(message)


def exception(message: str) -> None:
    """Log exception with traceback."""
    _logger.exception(message)


# Convenience functions with common prefixes
def log_success(message: str) -> None:
    """Log success message with ✓ prefix."""
    info(f"✓ {message}")


def log_error(message: str) -> None:
    """Log error message with ✗ prefix."""
    error(f"✗ {message}")


def log_step(step: str, message: str) -> None:
    """Log a step in the process."""
    info(f"[{step}] {message}")


def log_progress(current: int, total: int, message: str) -> None:
    """Log progress of a task."""
    info(f"[{current}/{total}] {message}")
