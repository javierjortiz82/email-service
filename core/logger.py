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
    - Startup banner with configuration summary

Author: Odiseo
Created: 2025-10-18
Version: 2.1.0
"""

import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from email_service.config.settings import EmailConfig

# Global configuration
_ROOT_LOGGER: logging.Logger | None = None
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

# P006 fix: Use tempfile for cross-platform compatibility
# Flag file to track if banner was already printed (for multi-worker scenarios)
_BANNER_FLAG_FILE = os.path.join(tempfile.gettempdir(), ".email_service_banner_printed")
_BANNER_FLAG_PATH = Path(_BANNER_FLAG_FILE)

# Module-level flag to track if this process printed the banner
_banner_printed_by_this_process = False

# ============================================================================
# ANSI Color Codes
# ============================================================================
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "white": "\033[97m",
    "red": "\033[31m",
    # Bright variants for better visibility
    "b_blue": "\033[94m",
    "b_cyan": "\033[96m",
    "b_green": "\033[92m",
    "b_yellow": "\033[93m",
    "b_magenta": "\033[95m",
}

# Color shortcuts for banner
_B = COLORS["bold"]
_R = COLORS["reset"]
_BC = COLORS["b_cyan"]
_BG = COLORS["b_green"]
_BY = COLORS["b_yellow"]
_BM = COLORS["b_magenta"]
_BB = COLORS["b_blue"]

# fmt: off
BANNER = f"""
{_B}{_BC} ███████╗{_BG} ███╗   ███╗{_BY}  █████╗ {_BM} ██╗{_BB} ██╗     {_R}
{_BC} ██╔════╝{_BG} ████╗ ████║{_BY} ██╔══██╗{_BM} ██║{_BB} ██║     {_R}
{_BC} █████╗  {_BG} ██╔████╔██║{_BY} ███████║{_BM} ██║{_BB} ██║     {_R}
{_BC} ██╔══╝  {_BG} ██║╚██╔╝██║{_BY} ██╔══██║{_BM} ██║{_BB} ██║     {_R}
{_BC} ███████╗{_BG} ██║ ╚═╝ ██║{_BY} ██║  ██║{_BM} ██║{_BB} ███████╗{_R}
{_BC} ╚══════╝{_BG} ╚═╝     ╚═╝{_BY} ╚═╝  ╚═╝{_BM} ╚═╝{_BB} ╚══════╝{_R}
{_R}"""  # noqa: E501
# fmt: on


def _try_acquire_banner_lock() -> bool:
    """Try to acquire banner lock atomically using exclusive file creation.

    Returns:
        True if this process should print the banner, False otherwise.
    """
    try:
        # O_CREAT | O_EXCL ensures atomic creation - fails if file exists
        fd = os.open(_BANNER_FLAG_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _cleanup_banner_flag() -> None:
    """Remove banner flag file for fresh container starts."""
    try:
        if _BANNER_FLAG_PATH.exists():
            _BANNER_FLAG_PATH.unlink()
    except OSError:
        pass


def _mask_password(password: str) -> str:
    """Mask password for display, showing only first and last char.

    Args:
        password: Password to mask.

    Returns:
        Masked password string.
    """
    if not password:
        return "(not set)"
    if len(password) <= 2:
        return "***"
    return f"{password[0]}{'*' * (len(password) - 2)}{password[-1]}"


def print_banner() -> None:
    """Print the service startup banner."""
    global _banner_printed_by_this_process  # noqa: PLW0603
    if not _try_acquire_banner_lock():
        return

    _banner_printed_by_this_process = True
    print(BANNER)
    print(f"{COLORS['dim']}{'─' * 72}{COLORS['reset']}")
    print(
        f"{COLORS['cyan']}{COLORS['bold']}  "
        f"Odiseo Email Microservice{COLORS['reset']}"
    )
    print(f"{COLORS['dim']}{'─' * 72}{COLORS['reset']}\n")


def print_config_summary(settings: "EmailConfig") -> None:
    """Print a formatted configuration summary organized by categories.

    Args:
        settings: EmailConfig instance with loaded configuration.
    """
    if not _banner_printed_by_this_process:
        return  # Banner wasn't printed by this process

    c = COLORS

    def _line(label: str, value: str, color: str = "cyan") -> None:
        print(f"  {c['dim']}│{c['reset']} {label:<26} {c[color]}{value}{c['reset']}")

    def _header(icon: str, title: str, color: str) -> None:
        print(f"\n  {c[color]}{icon} {title}{c['reset']}")
        print(f"  {c['dim']}├{'─' * 50}{c['reset']}")

    # =========================================================================
    # Service Configuration
    # =========================================================================
    _header("▶", "Service Configuration", "green")
    _line("Service Name", settings.SERVICE_NAME)
    _line("Version", settings.SERVICE_VERSION)
    _line("Host", settings.API_HOST)
    _line("Port", str(settings.API_PORT))

    # =========================================================================
    # Database Configuration
    # =========================================================================
    _header("▶", "Database Configuration", "blue")
    # Mask password in DATABASE_URL for display
    db_url = settings.DATABASE_URL
    if "@" in db_url:
        # postgresql://user:pass@host:port/db -> postgresql://user:***@host:port/db
        parts = db_url.split("@")
        auth_part = parts[0]
        if ":" in auth_part.split("//")[-1]:
            user_pass = auth_part.split("//")[-1]
            user = user_pass.split(":")[0]
            masked_url = f"{auth_part.split('//')[0]}//{user}:***@{parts[1]}"
        else:
            masked_url = db_url
    else:
        masked_url = db_url
    _line("Database URL", masked_url[:45] + "..." if len(masked_url) > 45 else masked_url)
    _line("Schema", settings.SCHEMA_NAME)

    # =========================================================================
    # SMTP Configuration
    # =========================================================================
    _header("▶", "SMTP Configuration", "magenta")
    _line("Host", settings.SMTP_HOST)
    _line("Port", str(settings.SMTP_PORT))
    _line("User", settings.SMTP_USER or "(not set)", "yellow" if not settings.SMTP_USER else "cyan")
    _line("Password", _mask_password(settings.SMTP_PASSWORD), "yellow" if not settings.SMTP_PASSWORD else "cyan")
    _line("From Email", settings.SMTP_FROM_EMAIL)
    _line("From Name", settings.SMTP_FROM_NAME)
    _line("TLS Enabled", str(settings.SMTP_USE_TLS).lower(), "green" if settings.SMTP_USE_TLS else "yellow")
    _line("Timeout", f"{settings.SMTP_TIMEOUT}s")

    # =========================================================================
    # Worker Configuration
    # =========================================================================
    _header("▶", "Worker Configuration", "cyan")
    _line("Poll Interval", f"{settings.EMAIL_WORKER_POLL_INTERVAL}s")
    _line("Batch Size", str(settings.EMAIL_WORKER_BATCH_SIZE))
    _line("Max Retry Attempts", str(settings.EMAIL_RETRY_MAX_ATTEMPTS))
    _line("Backoff (initial)", f"{settings.EMAIL_RETRY_BACKOFF_SECONDS}s")

    # =========================================================================
    # Logging Configuration
    # =========================================================================
    _header("▶", "Logging Configuration", "yellow")
    _line("Level", settings.LOG_LEVEL, "green")
    _line("Log to File", str(settings.LOG_TO_FILE).lower())
    _line("Directory", settings.LOG_DIR)
    _line("Max File Size", f"{settings.LOG_MAX_SIZE_MB} MB")
    _line("Backup Count", str(settings.LOG_BACKUP_COUNT))

    # =========================================================================
    # Footer
    # =========================================================================
    print(f"\n{c['dim']}{'─' * 72}{c['reset']}")
    print(
        f"  {c['green']}{c['bold']}✓ Service ready{c['reset']} "
        f"{c['dim']}│{c['reset']} "
        f"Docs: {c['cyan']}http://localhost:{settings.API_PORT}/docs{c['reset']}"
    )
    print(f"{c['dim']}{'─' * 72}{c['reset']}\n")


def setup_logging(
    log_dir: Path | None = None,
    log_level: str = "INFO",
    file_level: str = "DEBUG",
    console_level: str = "INFO",
    enable_file: bool = True,
    settings: Optional["EmailConfig"] = None,
) -> None:
    """Configure root logger with file and console handlers.

    Should be called once at application startup (e.g., in EmailWorker.__init__).

    Args:
        log_dir: Directory for log files. Defaults to email_service/logs.
        log_level: Root logger level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        file_level: File handler level (usually DEBUG for comprehensive logging).
        console_level: Console handler level (usually INFO to reduce noise).
        enable_file: Whether to write logs to files.
        settings: Optional EmailConfig for printing configuration summary.

    Example:
        setup_logging(
            log_level="INFO",
            file_level="DEBUG",
            console_level="WARNING",  # Only show warnings and errors on console
            settings=config,
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

    # Print startup banner and config summary
    print_banner()
    if settings:
        print_config_summary(settings)


def get_logger(name: str, log_level: str | None = None) -> logging.Logger:
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
    email_id: int | None = None,
    recipient: str | None = None,
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
