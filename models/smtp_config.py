"""SMTP configuration model.

Defines Pydantic model for SMTP server configuration and validation.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from pydantic import BaseModel, EmailStr, Field, field_validator


class SMTPConfig(BaseModel):
    """SMTP server configuration model.

    Validates and stores SMTP connection parameters.

    Attributes:
        host: SMTP server hostname.
        port: SMTP server port (1-65535).
        username: SMTP authentication username (optional).
        password: SMTP authentication password.
        from_email: Sender email address.
        from_name: Sender display name.
        use_tls: Whether to use TLS encryption.
        timeout: Connection timeout in seconds.
    """

    host: str = Field(..., min_length=1, description="SMTP server hostname")
    port: int = Field(..., ge=1, le=65535, description="SMTP server port")
    username: str = Field(default="", description="SMTP authentication username")
    password: str = Field(..., description="SMTP authentication password")
    from_email: EmailStr = Field(..., description="Sender email address")
    from_name: str = Field(default="Odiseo", description="Sender display name")
    use_tls: bool = Field(default=True, description="Use TLS encryption")
    timeout: int = Field(
        default=30, ge=5, le=120, description="Connection timeout (seconds)"
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password is not empty.

        Args:
            v: Password to validate.

        Returns:
            Validated password.

        Raises:
            ValueError: If password is empty or whitespace.
        """
        if not v or not v.strip():
            raise ValueError("SMTP password cannot be empty")
        return v
