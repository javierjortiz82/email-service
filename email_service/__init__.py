"""Email Service - Asynchronous email delivery system for bookings.

Provides a robust email queue system with:
- SMTP email delivery (Gmail, SendGrid, AWS SES)
- Template-based email rendering (Jinja2)
- Automatic retry with exponential backoff
- Scheduled emails (reminders, delayed sends)
- Status tracking (pending → processing → sent/failed)

Architecture:
    - PostgreSQL queue table (email_queue)
    - Worker service (polls queue every N seconds)
    - SMTP client wrapper
    - Jinja2 template renderer
    - Connection pooling with psycopg2

Modules:
    - core: Exceptions, logger, base utilities
    - config: Pydantic v2 settings
    - models: Data models (EmailRecord, requests, contexts)
    - clients: External integrations (SMTP)
    - database: Queue operations (PostgreSQL)
    - templates: Email template rendering (Jinja2)
    - worker: Email processing daemon

Usage:
    # Enqueue an email
    from email_service.database import EmailQueueManager
    from email_service.models import EmailType

    queue = EmailQueueManager()
    email_id = queue.enqueue_email(
        email_type=EmailType.BOOKING_CREATED,
        recipient_email="customer@example.com",
        recipient_name="John Doe",
        subject="Booking Confirmed",
        body_html="<h1>Your booking is confirmed!</h1>",
        template_context={"booking_id": 123, "service": "Consultation"}
    )

    # Run worker (in Docker container)
    from email_service.worker import EmailWorker
    import asyncio

    worker = EmailWorker()
    await worker.run()

Author: Odiseo
Created: 2025-10-18
Version: 2.0.0
"""

__version__ = "2.0.0"

# Clients
from email_service.clients import SMTPClient

# Configuration
from email_service.config import EmailConfig

# Core utilities
from email_service.core import (
    EmailConfigError,
    EmailQueueError,
    EmailServiceError,
    SMTPClientError,
    TemplateRenderError,
    get_logger,
)

# Database
from email_service.database import EmailQueueManager

# Models
from email_service.models import (
    BookingCancelledContext,
    BookingCreatedContext,
    BookingRescheduledContext,
    EmailCreateRequest,
    EmailRecord,
    EmailStats,
    EmailStatus,
    EmailTemplateContext,
    EmailType,
    ReminderContext,
    SMTPConfig,
)

# Templates
from email_service.templates import TemplateRenderer

# Worker
from email_service.worker import EmailWorker

__all__ = [
    # Version
    "__version__",
    # Core exceptions
    "EmailServiceError",
    "EmailConfigError",
    "EmailQueueError",
    "SMTPClientError",
    "TemplateRenderError",
    "get_logger",
    # Configuration
    "EmailConfig",
    # Models - Enums
    "EmailStatus",
    "EmailType",
    # Models - Core
    "EmailRecord",
    "EmailCreateRequest",
    "SMTPConfig",
    "EmailStats",
    # Models - Context
    "EmailTemplateContext",
    "BookingCreatedContext",
    "BookingCancelledContext",
    "BookingRescheduledContext",
    "ReminderContext",
    # Clients
    "SMTPClient",
    # Database
    "EmailQueueManager",
    # Templates
    "TemplateRenderer",
    # Worker
    "EmailWorker",
]
