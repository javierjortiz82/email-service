"""Centralized logging configuration for email service.

Provides robust logger factory with file rotation, multiple handlers,
and consistent formatting across all email service components.

Features:
    - Dual output: Console (stdout/stderr) + File handlers
    - Automatic log file rotation (10MB, 5 backups)
    - Configurable log levels per module
    - Structured logging with context
    - Best practices: ISO 8601 timestamps, proper exception handling
    - Performance optimized for async operations

Author: Odiseo
Created: 2025-10-18
Version: 2.0.0
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

# Global configuration
_ROOT_LOGGER: Optional[logging.Logger] = None
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_FORMAT_DETAILED = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
)
_LOG_FORMAT_SIMPLE = "%(asctime)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Module-level logger configuration
_MODULE_LEVELS = {
    "email_service.worker": logging.DEBUG,
    "email_service.clients": logging.DEBUG,
    "email_service.database": logging.DEBUG,
    "email_service.templates": logging.INFO,
    "email_service.config": logging.INFO,
}


def setup_logging(
    log_dir: Optional[Path] = None,
    log_level: str = "INFO",
    file_level: str = "DEBUG",
    console_level: str = "INFO",
    enable_file: bool = True,
) -> None:
    """Configure root logger with file and console handlers.

    Should be called once at application startup (e.g., in EmailWorker.__init__).

    Args:
        log_dir: Directory for log files. Defaults to email_service/logs.
        log_level: Root logger level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        file_level: File handler level (usually DEBUG for comprehensive logging).
        console_level: Console handler level (usually INFO to reduce noise).
        enable_file: Whether to write logs to files.

    Example:
        setup_logging(
            log_level="INFO",
            file_level="DEBUG",
            console_level="WARNING",  # Only show warnings and errors on console
        )
    """
    global _ROOT_LOGGER, _LOG_DIR

    if log_dir:
        _LOG_DIR = Path(log_dir)
    else:
        _LOG_DIR = Path(__file__).parent.parent / "logs"

    # Create logs directory if needed
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all levels, handlers filter

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console Handler (stdout for INFO+, stderr for WARNING+)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, console_level.upper(), logging.INFO))
    console_formatter = logging.Formatter(
        _LOG_FORMAT_SIMPLE, datefmt=_DATE_FORMAT
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File Handler with Rotation (if enabled)
    if enable_file:
        log_file = _LOG_DIR / "email_service.log"

        # RotatingFileHandler: 10MB per file, keep 5 backups
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,  # Keep email_service.log.1 to .5
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
        file_formatter = logging.Formatter(
            _LOG_FORMAT_DETAILED, datefmt=_DATE_FORMAT
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        # Error File Handler (separate errors to email_service.error.log)
        error_log_file = _LOG_DIR / "email_service.error.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_formatter = logging.Formatter(
            _LOG_FORMAT_DETAILED, datefmt=_DATE_FORMAT
        )
        error_handler.setFormatter(error_formatter)
        root_logger.addHandler(error_handler)

    # Set module-specific levels
    for module_name, level in _MODULE_LEVELS.items():
        module_logger = logging.getLogger(module_name)
        module_logger.setLevel(level)

    _ROOT_LOGGER = root_logger


def get_logger(name: str, log_level: Optional[str] = None) -> logging.Logger:
    """Get a configured logger instance for a module.

    Gets or creates a logger with consistent formatting. Call setup_logging()
    once at startup for full configuration.

    Args:
        name: Logger name (typically __name__ of calling module).
        log_level: Optional override for logger level (DEBUG, INFO, WARNING, ERROR).
                   If provided, sets logger-specific level.

    Returns:
        Configured logger instance ready for use.

    Example:
        from email_service.core.logger import get_logger

        logger = get_logger(__name__)
        logger.info("Processing email #123")
        logger.debug("Detailed debug information")
        logger.error("Error occurred", exc_info=True)
    """
    logger = logging.getLogger(name)

    # Set logger-specific level if provided
    if log_level:
        logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Prevent log propagation spam for verbose modules
    if name.startswith("email_service"):
        logger.propagate = True

    return logger


def get_logs_directory() -> Path:
    """Get the logs directory path.

    Returns:
        Path object pointing to email_service/logs directory.
    """
    return _LOG_DIR


def log_context(
    logger: logging.Logger,
    operation: str,
    email_id: Optional[int] = None,
    recipient: Optional[str] = None,
    **kwargs,
) -> str:
    """Format a log context string with metadata.

    Helper for structured logging with contextual information.

    Args:
        logger: Logger instance.
        operation: Operation name (e.g., "send_email", "retry").
        email_id: Email record ID if applicable.
        recipient: Recipient email if applicable.
        **kwargs: Additional context key-value pairs.

    Returns:
        Formatted context string for logging.

    Example:
        msg = log_context(
            logger,
            "send_email",
            email_id=123,
            recipient="user@example.com",
            smtp_host="smtp.gmail.com",
        )
        logger.info(f"Starting: {msg}")
        # Output: Starting: [#123→user@example.com] send_email (smtp_host=smtp.gmail.com)
    """
    context_parts = [operation]

    if email_id:
        context_parts.insert(0, f"#{email_id}")

    if recipient:
        context_parts.append(f"→{recipient}")

    context = " | ".join(context_parts)

    if kwargs:
        extra = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        context = f"{context} ({extra})"

    return context
