"""Email service configuration with Pydantic v2.

Manages SMTP settings, database connection, and worker configuration
loaded from environment variables or .env file.

All settings can be overridden via environment variables.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from email_service.core.exceptions import EmailConfigError


class EmailConfig(BaseSettings):
    """Email service configuration.

    Loads settings from environment variables and .env file using Pydantic v2.
    All settings are case-sensitive and strictly validated.

    Attributes:
        DATABASE_URL: PostgreSQL connection string.
        SCHEMA_NAME: PostgreSQL schema containing email_queue table.
        SMTP_HOST: SMTP server hostname.
        SMTP_PORT: SMTP server port (1-65535).
        SMTP_USER: SMTP authentication username.
        SMTP_PASSWORD: SMTP authentication password.
        SMTP_FROM_EMAIL: Sender email address.
        SMTP_FROM_NAME: Sender display name.
        SMTP_USE_TLS: Whether to use TLS encryption.
        SMTP_TIMEOUT: SMTP connection timeout in seconds.
        EMAIL_WORKER_POLL_INTERVAL: Queue poll interval in seconds.
        EMAIL_WORKER_BATCH_SIZE: Max emails per batch.
        EMAIL_RETRY_MAX_ATTEMPTS: Maximum retry attempts.
        EMAIL_RETRY_BACKOFF_SECONDS: Initial backoff duration.
        REMINDER_24H_ENABLED: Enable 24-hour reminders.
        REMINDER_1H_ENABLED: Enable 1-hour reminders.
        REMINDER_24H_SUBJECT: 24-hour reminder subject line.
        REMINDER_1H_SUBJECT: 1-hour reminder subject line.
        LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        LOG_TO_FILE: Whether to log to file.
        LOG_DIR: Directory for log files.
        TEMPLATE_DIR: Directory containing Jinja2 email templates.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ========================================================================
    # Service Configuration
    # ========================================================================
    SERVICE_NAME: str = Field(
        default="email-service",
        description="Name of the service",
    )
    SERVICE_VERSION: str = Field(
        default="1.0.0",
        description="Service version",
    )
    API_HOST: str = Field(
        default="0.0.0.0",
        description="API server host",
    )
    API_PORT: int = Field(
        default=8001,
        ge=1,
        le=65535,
        description="API server port",
    )

    # ========================================================================
    # Database Configuration
    # ========================================================================
    DATABASE_URL: str = Field(
        default="postgresql://mcp_user:mcp_password@localhost:5434/mcpdb",
        description="PostgreSQL connection string",
    )
    SCHEMA_NAME: str = Field(
        default="test",
        description="PostgreSQL schema name for email_queue table",
    )

    # ========================================================================
    # SMTP Configuration
    # ========================================================================
    SMTP_HOST: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname",
    )
    SMTP_PORT: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port",
    )
    SMTP_USER: str = Field(
        default="",
        description="SMTP authentication username",
    )
    SMTP_PASSWORD: str = Field(
        default="",
        description="SMTP authentication password",
    )
    SMTP_FROM_EMAIL: str = Field(
        default="noreply@odiseo.io",
        description="Sender email address",
    )
    SMTP_FROM_NAME: str = Field(
        default="Odiseo",
        description="Sender display name",
    )
    SMTP_USE_TLS: bool = Field(
        default=True,
        description="Whether to use TLS encryption",
    )
    SMTP_TIMEOUT: int = Field(
        default=30,
        ge=5,
        le=300,
        description="SMTP connection timeout in seconds",
    )

    # ========================================================================
    # Email Worker Configuration
    # ========================================================================
    EMAIL_WORKER_POLL_INTERVAL: int = Field(
        default=10,
        ge=1,
        le=3600,
        description="Seconds between queue polls",
    )
    EMAIL_WORKER_BATCH_SIZE: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Max emails per batch",
    )
    EMAIL_RETRY_MAX_ATTEMPTS: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts",
    )
    EMAIL_RETRY_BACKOFF_SECONDS: int = Field(
        default=300,
        ge=60,
        le=86400,
        description="Initial backoff duration in seconds",
    )

    # ========================================================================
    # Reminder Configuration
    # ========================================================================
    REMINDER_24H_ENABLED: bool = Field(
        default=True,
        description="Enable 24-hour appointment reminders",
    )
    REMINDER_1H_ENABLED: bool = Field(
        default=True,
        description="Enable 1-hour appointment reminders",
    )
    REMINDER_24H_SUBJECT: str = Field(
        default="Recordatorio: Cita mañana",
        description="24-hour reminder subject line",
    )
    REMINDER_1H_SUBJECT: str = Field(
        default="Recordatorio: Cita en 1 hora",
        description="1-hour reminder subject line",
    )

    # ========================================================================
    # Logging Configuration
    # ========================================================================
    LOG_LEVEL: str = Field(
        default="INFO",
        pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Logging level",
    )
    LOG_TO_FILE: bool = Field(
        default=True,
        description="Whether to log to file",
    )
    LOG_DIR: str = Field(
        default="./logs",
        description="Directory for log files",
    )
    LOG_MAX_SIZE_MB: int = Field(
        default=10,
        gt=0,
        description="Maximum log file size in megabytes",
    )
    LOG_BACKUP_COUNT: int = Field(
        default=5,
        gt=0,
        description="Number of backup log files to keep",
    )

    # ========================================================================
    # Template Configuration
    # ========================================================================
    TEMPLATE_DIR: str = Field(
        default_factory=lambda: str(Path(__file__).parent.parent / "templates"),
        description="Directory containing Jinja2 email templates",
    )

    @field_validator("SMTP_HOST")
    @classmethod
    def validate_smtp_host(cls, v: str) -> str:
        """Validate SMTP host is not empty.

        Args:
            v: SMTP hostname to validate.

        Returns:
            Validated SMTP hostname.

        Raises:
            ValueError: If hostname is empty or whitespace.
        """
        if not v.strip():
            raise ValueError("SMTP_HOST cannot be empty")
        return v.strip()

    @field_validator("SMTP_PASSWORD")
    @classmethod
    def validate_smtp_password(cls, v: str) -> str:
        """Validate and clean SMTP password.

        Automatically removes spaces from SMTP password (Gmail app passwords
        are displayed with spaces for readability but must be used without spaces).

        Args:
            v: Password value to validate.

        Returns:
            Validated and cleaned password (spaces removed).

        Examples:
            >>> # Gmail generates: "wrce fmkh xlvn jiht"
            >>> # Automatically converted to: "wrcefmkhxlvnjiht"
        """
        # Remove all spaces from password
        # Gmail app passwords are displayed with spaces but must be used without them
        return v.replace(" ", "")

    @field_validator("SMTP_USER")
    @classmethod
    def validate_smtp_user(cls, v: str) -> str:
        """Validate SMTP username.

        Args:
            v: Username value to validate.

        Returns:
            Validated username.
        """
        # Note: Username can be empty during initialization,
        # but will be validated later when needed
        return v

    @field_validator("SMTP_FROM_EMAIL")
    @classmethod
    def validate_from_email(cls, v: str) -> str:
        """Validate from_email is not empty.

        Args:
            v: From email to validate.

        Returns:
            Validated email.

        Raises:
            ValueError: If email is empty.
        """
        if not v.strip():
            raise ValueError("SMTP_FROM_EMAIL cannot be empty")
        return v.strip()

    def validate_smtp_config(self) -> None:
        """Validate complete SMTP configuration.

        Ensures all required SMTP settings are properly configured before
        attempting to send emails.

        Raises:
            EmailConfigError: If required SMTP settings are missing or invalid.
        """
        missing_fields = []

        if not self.SMTP_USER or not self.SMTP_USER.strip():
            missing_fields.append("SMTP_USER")

        if not self.SMTP_PASSWORD or not self.SMTP_PASSWORD.strip():
            missing_fields.append("SMTP_PASSWORD")

        if not self.SMTP_FROM_EMAIL or not self.SMTP_FROM_EMAIL.strip():
            missing_fields.append("SMTP_FROM_EMAIL")

        if missing_fields:
            raise EmailConfigError(
                f"Required SMTP settings missing: {', '.join(missing_fields)}. "
                f"Set these environment variables to enable email sending."
            )

    def get_smtp_config(self) -> dict[str, str | int | bool]:
        """Get SMTP configuration as dictionary.

        Returns a dictionary with all SMTP settings suitable for passing
        to SMTPClient initialization.

        Returns:
            Dictionary with SMTP configuration keys and values.
        """
        return {
            "host": self.SMTP_HOST,
            "port": self.SMTP_PORT,
            "username": self.SMTP_USER,
            "password": self.SMTP_PASSWORD,
            "from_email": self.SMTP_FROM_EMAIL,
            "from_name": self.SMTP_FROM_NAME,
            "use_tls": self.SMTP_USE_TLS,
            "timeout": self.SMTP_TIMEOUT,
        }
