"""Email creation request models.

Defines request models for creating emails to be added to the queue.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from email_service.models.email import EmailType
from pydantic import BaseModel, EmailStr, Field, field_validator


class EmailCreateRequest(BaseModel):
    """Request model for creating a new email in queue.

    Validates email creation parameters and ensures either pre-rendered
    content or template context is provided for delivery.

    Attributes:
        type: Email type (booking_created, reminder_24h, etc).
        recipient_email: Valid email address of recipient.
        recipient_name: Full name of recipient (optional).
        subject: Email subject line (1-500 characters).
        body_html: Pre-rendered HTML body (optional if template_context provided).
        body_text: Plain-text fallback (optional).
        booking_id: Related booking ID (optional).
        template_context: JSON dict for Jinja2 template rendering (optional).
        scheduled_for: When to send email (default: immediately).
        priority: Priority level 1-10 (1=highest, default=5).

    Validation:
        - Subject must not be empty or whitespace-only.
        - Either body_html or template_context must be provided.
        - Priority must be between 1 and 10.
    """

    type: EmailType = Field(..., description="Email type/category")
    recipient_email: EmailStr = Field(..., description="Recipient email")
    recipient_name: str | None = Field(default=None, description="Recipient name")
    subject: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Email subject line",
    )
    body_html: str = Field(
        default="",
        max_length=1000000,
        description="HTML email body",
    )
    body_text: str | None = Field(default=None, description="Plain-text body")
    booking_id: int | None = Field(default=None, description="Related booking ID")
    template_context: dict[str, Any] | None = Field(
        default=None, description="Jinja2 template context"
    )
    scheduled_for: datetime | None = Field(
        default=None, description="Scheduled send time"
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority level (1=highest, 10=lowest)",
    )

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        """Validate subject is not empty or whitespace-only.

        Args:
            v: Subject line to validate.

        Returns:
            Trimmed subject line.

        Raises:
            ValueError: If subject is empty or only whitespace.
        """
        if not v.strip():
            raise ValueError("Subject cannot be empty or whitespace")
        return v.strip()

    @field_validator("body_html")
    @classmethod
    def validate_body_html_or_template(cls, v: str, info) -> str:
        """Validate either body_html or template_context is provided.

        Ensures that at least one content source (pre-rendered HTML or
        template context for rendering) is available.

        Args:
            v: HTML body to validate.
            info: Validation context with all field data.

        Returns:
            HTML body value.

        Raises:
            ValueError: If both body_html and template_context are empty.
        """
        template_context = info.data.get("template_context")

        if not v.strip() and not template_context:
            raise ValueError(
                "Either body_html or template_context must be provided. "
                "If body_html is empty, template_context will be used "
                "by the worker to render the email."
            )
        return v
