"""Models module for email service.

Defines Pydantic v2 data models for email records, requests, template contexts,
and SMTP configuration.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from email_service.models.context import (
    BookingCancelledContext,
    BookingCreatedContext,
    BookingRescheduledContext,
    EmailTemplateContext,
    ReminderContext,
)
from email_service.models.email import EmailRecord, EmailStatus, EmailType
from email_service.models.requests import EmailCreateRequest
from email_service.models.smtp_config import SMTPConfig
from email_service.models.stats import EmailStats

__all__ = [
    # Enums
    "EmailStatus",
    "EmailType",
    # Models
    "EmailRecord",
    "EmailCreateRequest",
    "SMTPConfig",
    "EmailStats",
    # Context models
    "EmailTemplateContext",
    "BookingCreatedContext",
    "BookingCancelledContext",
    "BookingRescheduledContext",
    "ReminderContext",
]
