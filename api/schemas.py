"""API request and response schemas.

Pydantic models for API validation and serialization.

Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class EmailRequest(BaseModel):
    """Request model for POST /emails endpoint."""

    client_message_id: str | None = Field(
        default=None,
        description="Optional client-provided message ID for tracking",
    )
    to: list[EmailStr] = Field(
        ...,
        min_length=1,
        description="List of recipient email addresses",
    )
    cc: list[EmailStr] = Field(
        default_factory=list,
        description="List of CC email addresses",
    )
    bcc: list[EmailStr] = Field(
        default_factory=list,
        description="List of BCC email addresses",
    )
    subject: str = Field(
        ...,
        min_length=1,
        max_length=998,
        description="Email subject line",
    )
    body: str = Field(
        ...,
        min_length=1,
        description="HTML email body",
    )
    template_id: str | None = Field(
        default=None,
        description="Template ID for dynamic content",
    )
    template_vars: dict[str, Any] = Field(
        default_factory=dict,
        description="Variables for template rendering",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom metadata for tracking",
    )


class EmailResponse(BaseModel):
    """Response model for POST /emails endpoint."""

    status: str = Field(description="Request status (accepted)")
    queued: bool = Field(description="Whether email was queued")
    message_id: str = Field(description="Internal message ID")
    detail: str = Field(description="Status message")
    # P003 fix: Use lambda to capture timestamp at instantiation time
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class QueueStatusResponse(BaseModel):
    """Response model for GET /queue/status endpoint."""

    pending: int = Field(description="Emails waiting to be processed")
    scheduled: int = Field(description="Emails scheduled for retry")
    processing: int = Field(description="Emails currently being sent")
    sent: int = Field(description="Successfully sent emails")
    failed: int = Field(description="Permanently failed emails")
    # P003 fix: Use lambda to capture timestamp at instantiation time
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class HealthResponse(BaseModel):
    """Response model for GET /health endpoint."""

    status: str = Field(description="Overall service status")
    db: str = Field(description="Database connection status")
    email_provider: str = Field(description="SMTP connection status")
    version: str = Field(description="Service version")
    # P003 fix: Use lambda to capture timestamp at instantiation time
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class ProcessQueueResponse(BaseModel):
    """Response model for POST /queue/process endpoint."""

    processed: int = Field(description="Number of emails successfully sent")
    failed: int = Field(description="Number of emails that failed")
    retried: int = Field(description="Number of emails scheduled for retry")
    detail: str = Field(description="Processing summary")
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str = Field(description="Error type")
    message: str = Field(description="Error description")
    code: str = Field(description="Error code")
    # P003 fix: Use lambda to capture timestamp at instantiation time
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
