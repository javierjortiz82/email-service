"""Core module for email service.

Provides foundational utilities, exceptions, and robust logging configuration.

Author: Odiseo
Created: 2025-10-18
Version: 2.0.0
"""

from email_service.core.exceptions import (
    EmailConfigError,
    EmailQueueError,
    EmailServiceError,
    SMTPClientError,
    TemplateRenderError,
)
from email_service.core.logger import (
    get_logger,
    get_logs_directory,
    log_context,
    setup_logging,
)

__all__ = [
    # Exceptions
    "EmailServiceError",
    "EmailConfigError",
    "EmailQueueError",
    "SMTPClientError",
    "TemplateRenderError",
    # Logging
    "get_logger",
    "setup_logging",
    "get_logs_directory",
    "log_context",
]
