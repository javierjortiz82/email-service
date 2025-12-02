"""Custom exceptions for email service.

Defines specific exception types for different email service failures
to enable precise error handling and logging.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""


class EmailServiceError(Exception):
    """Base exception for all email service errors.

    Serves as the parent class for all custom exceptions in the email service,
    allowing consumers to catch all email-related errors with a single except block.

    Example:
        try:
            queue.enqueue_email(...)
        except EmailServiceError as e:
            logger.error(f"Email service error: {e}")
    """

    pass


class EmailConfigError(EmailServiceError):
    """Exception raised for configuration errors.

    Indicates invalid or missing configuration in EmailConfig or SMTP settings.

    Attributes:
        message (str): Description of the configuration error.

    Example:
        raise EmailConfigError("SMTP_USER environment variable not set")
    """

    pass


class EmailQueueError(EmailServiceError):
    """Exception raised for database queue operations.

    Indicates failures during email enqueueing, status updates, or retrieval
    from PostgreSQL.

    Attributes:
        message (str): Description of the database error.
        email_id (int, optional): ID of the affected email record.

    Example:
        raise EmailQueueError(
            f"Failed to enqueue email for recipient {email}",
            email_id=123
        )
    """

    def __init__(self, message: str, email_id: int | None = None):
        """Initialize queue error.

        Args:
            message: Error description.
            email_id: Optional ID of affected email record.
        """
        super().__init__(message)
        self.email_id = email_id


class SMTPClientError(EmailServiceError):
    """Exception raised for SMTP connection/delivery failures.

    Indicates problems with SMTP connection, authentication, or email sending.

    Attributes:
        message (str): Description of the SMTP error.
        is_transient (bool): Whether error is temporary (retry recommended).

    Example:
        raise SMTPClientError(
            "Connection timeout to smtp.gmail.com:587",
            is_transient=True
        )
    """

    def __init__(self, message: str, is_transient: bool = False):
        """Initialize SMTP client error.

        Args:
            message: Error description.
            is_transient: Whether error is temporary and retryable.
        """
        super().__init__(message)
        self.is_transient = is_transient


class TemplateRenderError(EmailServiceError):
    """Exception raised for template rendering failures.

    Indicates problems rendering Jinja2 templates or missing template files.

    Attributes:
        message (str): Description of the template error.
        template_name (str, optional): Name of the template that failed.

    Example:
        raise TemplateRenderError(
            "Missing variable: customer_name",
            template_name="booking_created.html"
        )
    """

    def __init__(self, message: str, template_name: str | None = None):
        """Initialize template render error.

        Args:
            message: Error description.
            template_name: Optional name of the template that failed.
        """
        super().__init__(message)
        self.template_name = template_name
