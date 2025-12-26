"""Email data models.

Defines core email models including status enums, email types, and
email queue records.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EmailStatus(str, Enum):
    """Email delivery status enumeration.

    Represents the lifecycle states of an email in the queue system.

    Attributes:
        PENDING: Waiting in queue for processing.
        SCHEDULED: Waiting for scheduled_for timestamp to arrive.
        PROCESSING: Currently being sent via SMTP.
        SENT: Successfully delivered to recipient.
        FAILED: Delivery failed after max retries exceeded.
    """

    PENDING = "pending"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class EmailType(str, Enum):
    """Email notification type enumeration.

    Categorizes different types of emails sent by the system.

    Attributes:
        TRANSACTIONAL: Generic transactional email via API.
        BOOKING_CREATED: Confirmation of new booking.
        BOOKING_CANCELLED: Notification of booking cancellation.
        BOOKING_RESCHEDULED: Notification of booking date/time change.
        REMINDER_24H: 24-hour appointment reminder.
        REMINDER_1H: 1-hour appointment reminder.
        REMINDER_CUSTOM: Custom reminder (flexible timing).
        OTP_VERIFICATION: OTP email verification code.
    """

    TRANSACTIONAL = "transactional"
    BOOKING_CREATED = "booking_created"
    BOOKING_CANCELLED = "booking_cancelled"
    BOOKING_RESCHEDULED = "booking_rescheduled"
    REMINDER_24H = "reminder_24h"
    REMINDER_1H = "reminder_1h"
    REMINDER_CUSTOM = "reminder_custom"
    OTP_VERIFICATION = "otp_verification"


class EmailRecord(BaseModel):
    """Email queue record model.

    Represents a single email in the PostgreSQL queue system, tracking
    all metadata needed for delivery and retry logic.

    Attributes:
        id: Unique email record ID from database.
        type: Category of email (booking_created, reminder_24h, etc).
        recipient_email: Recipient email address.
        recipient_name: Recipient full name (optional).
        subject: Email subject line (max 500 chars).
        body_html: HTML-formatted email body.
        body_text: Plain-text email body (optional fallback).
        status: Current delivery status (pending, processing, sent, failed).
        retry_count: Number of failed delivery attempts.
        max_retries: Maximum allowed retry attempts (default: 3).
        last_error: Error message from last failed attempt.
        next_retry_at: Timestamp of next retry attempt.
        scheduled_for: Timestamp when email should be sent (default: now).
        sent_at: Timestamp when email was successfully delivered.
        priority: Priority level (1=highest, 10=lowest). Default: 5.
        booking_id: Related booking ID if applicable.
        template_context: JSON context dict for Jinja2 template rendering.
        created_at: When email was enqueued.
        updated_at: Last update timestamp.
    """

    id: int = Field(..., description="Unique email record ID")
    type: EmailType = Field(..., alias="email_type", description="Email type/category")
    recipient_email: str = Field(..., description="Recipient email address")
    recipient_name: str | None = Field(default=None, description="Recipient full name")
    subject: str = Field(..., max_length=500, description="Email subject line")
    body_html: str = Field(..., description="HTML-formatted email body")
    body_text: str | None = Field(default=None, description="Plain-text email body")
    status: EmailStatus = Field(
        default=EmailStatus.PENDING, description="Current delivery status"
    )
    retry_count: int = Field(default=0, ge=0, description="Number of failed attempts")
    max_retries: int = Field(
        default=3, ge=1, le=10, description="Maximum retry attempts"
    )
    last_error: str | None = Field(default=None, description="Last error message")
    next_retry_at: datetime | None = Field(
        default=None, description="Timestamp of next retry"
    )
    scheduled_for: datetime | None = Field(
        default=None, description="Scheduled send timestamp"
    )
    sent_at: datetime | None = Field(
        default=None, description="Delivery success timestamp"
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority level (1=highest, 10=lowest)",
    )
    booking_id: int | None = Field(default=None, description="Related booking ID")
    template_context: dict[str, Any] | None = Field(
        default=None, description="JSON context for template rendering"
    )
    created_at: datetime = Field(..., description="Enqueue timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {
        "from_attributes": True,  # Pydantic v2
        "populate_by_name": True,  # Allow both field name and alias
        "use_enum_values": False,
    }
