"""Email Microservice API.

FastAPI application providing endpoints for email operations:
- POST /emails: Send an email (queued for delivery)
- GET /queue/status: Get queue statistics
- GET /health: Service health check

Security features:
- API key authentication
- Rate limiting
- Sanitized error responses

Author: Odiseo
Version: 2.0.0
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from email_service.api.schemas import (
    EmailRequest,
    EmailResponse,
    ErrorResponse,
    HealthResponse,
    ProcessQueueResponse,
    QueueStatusResponse,
)
from email_service.clients.smtp import SMTPClient
from email_service.config import EmailConfig
from email_service.core.logger import get_logger, setup_logging
from email_service.database.queue import EmailQueueManager
from email_service.models.email import EmailRecord, EmailStatus, EmailType
from email_service.templates.renderer import TemplateRenderer
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

logger = get_logger(__name__)


# =============================================================================
# Application State (Dependency Injection)
# =============================================================================
@dataclass
class AppState:
    """Application state container for dependency injection."""

    config: EmailConfig
    queue_manager: EmailQueueManager | None = None


app_state: AppState | None = None


def get_config() -> EmailConfig:
    """Dependency: Get application configuration."""
    if not app_state or not app_state.config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )
    return app_state.config


def get_queue_manager() -> EmailQueueManager:
    """Dependency: Get queue manager instance."""
    if not app_state or not app_state.queue_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )
    return app_state.queue_manager


# =============================================================================
# Rate Limiting
# =============================================================================
@dataclass
class RateLimiter:
    """Thread-safe in-memory rate limiter using sliding window."""

    requests_per_minute: int = 60
    requests_per_second: int = 10
    # M004 fix: Proper type hint for _requests dict
    _requests: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _clean_old_requests(self, client_id: str, window_seconds: int) -> None:
        """Remove requests outside the time window."""
        now = time.time()
        self._requests[client_id] = [
            t for t in self._requests[client_id] if now - t < window_seconds
        ]
        # D001 fix: Remove empty client entries to prevent memory leak
        if not self._requests[client_id]:
            del self._requests[client_id]

    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed under rate limits (thread-safe)."""
        # D002 fix: Use lock for thread safety
        with self._lock:
            now = time.time()

            # Clean requests older than 60 seconds
            self._clean_old_requests(client_id, 60)

            # Check per-second limit (last 1 second)
            recent_second = [
                t for t in self._requests.get(client_id, []) if now - t < 1
            ]
            if len(recent_second) >= self.requests_per_second:
                return False

            # Check per-minute limit
            if len(self._requests.get(client_id, [])) >= self.requests_per_minute:
                return False

            # Record this request
            self._requests[client_id].append(now)
            return True

    def get_client_id(self, request: Request) -> str:
        """Get client identifier from request."""
        # Use X-Forwarded-For if behind proxy, otherwise use client host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            # D012 fix: Safe attribute access
            client_ip = (
                getattr(request.client, "host", "unknown")
                if request.client
                else "unknown"
            )

        # Hash the IP for privacy
        return hashlib.sha256(client_ip.encode()).hexdigest()[:16]


rate_limiter = RateLimiter()


# =============================================================================
# API Key Authentication
# =============================================================================
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Depends(API_KEY_HEADER)],
    config: Annotated[EmailConfig, Depends(get_config)],
) -> bool:
    """Verify API key if authentication is enabled.

    Returns True if:
    - API_KEY is not configured (auth disabled)
    - API_KEY matches the provided key
    """
    configured_key = getattr(config, "API_KEY", None)

    # If no API key configured, authentication is disabled
    if not configured_key:
        return True

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # M001 fix: Use timing-safe comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, configured_key):
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return True


# =============================================================================
# Rate Limit Middleware
# =============================================================================
async def check_rate_limit(request: Request) -> None:
    """Middleware to check rate limits."""
    # Skip rate limiting for health checks
    if request.url.path == "/health":
        return

    client_id = rate_limiter.get_client_id(request)
    if not rate_limiter.is_allowed(client_id):
        logger.warning(f"Rate limit exceeded for client: {client_id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": "60"},
        )


# =============================================================================
# Module-level Configuration (D006 fix: Single instantiation)
# =============================================================================
_config = EmailConfig()


# =============================================================================
# Lifespan Context Manager
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    global app_state

    # Startup - use module-level config
    app_state = AppState(config=_config)

    setup_logging(
        log_level=_config.LOG_LEVEL,
        enable_file=_config.LOG_TO_FILE,
        settings=_config,
    )

    try:
        app_state.queue_manager = EmailQueueManager(_config)
        logger.info(f"Database connected: {_config.SCHEMA_NAME}.email_queue")
    except Exception as e:
        logger.error(f"Failed to start API: {e}")
        raise

    yield  # Application runs here

    # Shutdown
    logger.info(f"Shutting down {_config.SERVICE_NAME}...")
    if app_state and app_state.queue_manager:
        app_state.queue_manager.close()
    logger.info(f"{_config.SERVICE_NAME} stopped")


# =============================================================================
# FastAPI Application
# =============================================================================
def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    application = FastAPI(
        title=_config.SERVICE_NAME,
        description="Production-ready email sending microservice with queue management",
        version=_config.SERVICE_VERSION,
        lifespan=lifespan,
    )

    return application


app = create_app()


# =============================================================================
# Template Type Mapping
# =============================================================================
TEMPLATE_TYPE_MAP = {
    "otp_verification": EmailType.OTP_VERIFICATION,
    "booking_created": EmailType.BOOKING_CREATED,
    "booking_cancelled": EmailType.BOOKING_CANCELLED,
    "booking_rescheduled": EmailType.BOOKING_RESCHEDULED,
    "reminder_24h": EmailType.REMINDER_24H,
    "reminder_1h": EmailType.REMINDER_1H,
}


# =============================================================================
# API Endpoints
# =============================================================================
@app.post(
    "/emails",
    response_model=EmailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    dependencies=[Depends(check_rate_limit)],
)
async def send_email(
    request: EmailRequest,
    queue_manager: Annotated[EmailQueueManager, Depends(get_queue_manager)],
    _auth: Annotated[bool, Depends(verify_api_key)],
) -> EmailResponse:
    """Queue an email for delivery.

    Requires API key authentication if API_KEY is configured.
    Subject to rate limiting (60 requests/minute, 10 requests/second).
    """
    try:
        message_id = request.client_message_id or str(uuid.uuid4())

        # Determine email type based on template_id
        email_type = EmailType.TRANSACTIONAL
        if request.template_id:
            email_type = TEMPLATE_TYPE_MAP.get(
                request.template_id, EmailType.TRANSACTIONAL
            )

        for recipient in request.to:
            queue_manager.enqueue_email(
                email_type=email_type,
                recipient_email=recipient,
                recipient_name=(
                    request.template_vars.get("recipient_name")
                    if request.template_vars
                    else None
                ),
                subject=request.subject,
                body_html=request.body,
                template_context=request.template_vars if request.template_id else None,
            )

        logger.info(
            f"Email queued: {message_id} to {len(request.to)} recipients "
            f"(type={email_type.value})"
        )

        return EmailResponse(
            status="accepted",
            queued=True,
            message_id=message_id,
            detail="Email stored in queue",
        )

    except HTTPException:
        raise
    except Exception as e:
        # Log full error details server-side
        logger.error(f"Failed to queue email: {e}", exc_info=True)
        # Return sanitized error to client (intentionally not chaining)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process email request",
        ) from None


@app.get(
    "/queue/status",
    response_model=QueueStatusResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
)
async def get_queue_status_endpoint(
    queue_manager: Annotated[EmailQueueManager, Depends(get_queue_manager)],
    config: Annotated[EmailConfig, Depends(get_config)],
    _auth: Annotated[bool, Depends(verify_api_key)],
) -> QueueStatusResponse:
    """Get email queue statistics.

    Requires API key authentication if API_KEY is configured.
    """
    try:
        counts = queue_manager.get_queue_stats()

        return QueueStatusResponse(
            pending=counts.get(EmailStatus.PENDING.value, 0),
            scheduled=counts.get(EmailStatus.SCHEDULED.value, 0),
            processing=counts.get(EmailStatus.PROCESSING.value, 0),
            sent=counts.get(EmailStatus.SENT.value, 0),
            failed=counts.get(EmailStatus.FAILED.value, 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        # Log full error details server-side
        logger.error(f"Failed to get queue status: {e}", exc_info=True)
        # Return sanitized error to client (intentionally not chaining)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve queue status",
        ) from None


@app.post(
    "/queue/process",
    response_model=ProcessQueueResponse,
    responses={500: {"model": ErrorResponse, "description": "Processing failed"}},
)
async def process_queue_endpoint(
    queue_manager: Annotated[EmailQueueManager, Depends(get_queue_manager)],
    config: Annotated[EmailConfig, Depends(get_config)],
    _auth: Annotated[bool, Depends(verify_api_key)],
    batch_size: int = 10,
) -> ProcessQueueResponse:
    """Process pending emails in the queue.

    This endpoint is designed for Cloud Run where background workers
    are not available. Call this endpoint via Cloud Scheduler to
    process the email queue periodically.

    Args:
        batch_size: Maximum emails to process (default: 10, max: 50)

    Requires API key or IAM authentication.
    """
    batch_size = min(max(batch_size, 1), 50)
    processed = 0
    failed = 0
    retried = 0

    try:
        # Validate SMTP config before processing
        config.validate_smtp_config()

        # Initialize SMTP client and template renderer
        smtp_client = SMTPClient()
        template_renderer = TemplateRenderer()

        # Get pending emails
        pending_emails = queue_manager.get_pending_emails(limit=batch_size)

        if not pending_emails:
            return ProcessQueueResponse(
                processed=0,
                failed=0,
                retried=0,
                detail="No pending emails in queue",
            )

        logger.info(f"Processing {len(pending_emails)} pending emails...")

        for email in pending_emails:
            try:
                # Prepare email content
                body_html, body_text = _prepare_email_content(
                    email, template_renderer, config
                )

                # Send via SMTP
                smtp_client.send_email(
                    recipient_email=email.recipient_email,
                    recipient_name=email.recipient_name,
                    subject=email.subject,
                    body_html=body_html,
                    body_text=body_text,
                )

                # Mark as sent
                queue_manager.update_email_status(
                    email.id, EmailStatus.SENT, sent_at=datetime.now()
                )
                processed += 1
                logger.info(f"Email {email.id} sent successfully")

            except Exception as e:
                error_msg = str(e)[:500]
                logger.error(f"Failed to send email {email.id}: {error_msg}")

                # Retry logic
                if email.retry_count < email.max_retries:
                    queue_manager.retry_email(
                        email.id,
                        error=error_msg,
                        backoff_seconds=config.EMAIL_RETRY_BACKOFF_SECONDS,
                    )
                    retried += 1
                else:
                    queue_manager.update_email_status(
                        email.id, EmailStatus.FAILED, error=error_msg
                    )
                    failed += 1

        # Cleanup SMTP connection
        smtp_client.close()

        detail = (
            f"Processed batch: {processed} sent, {retried} retried, {failed} failed"
        )
        logger.info(detail)

        return ProcessQueueResponse(
            processed=processed,
            failed=failed,
            retried=retried,
            detail=detail,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Queue processing error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process email queue",
        ) from None


def _prepare_email_content(
    email: EmailRecord,
    template_renderer: TemplateRenderer,
    config: EmailConfig,
) -> tuple[str, str | None]:
    """Prepare email content (render template or use pre-rendered)."""
    if email.template_context:
        try:
            email_type = (
                EmailType(email.type) if isinstance(email.type, str) else email.type
            )
        except ValueError:
            email_type = EmailType.TRANSACTIONAL

        body_html = template_renderer.render_html(email_type, email.template_context)
        body_text = template_renderer.render_text(email_type, email.template_context)
    else:
        body_html = email.body_html
        body_text = email.body_text

    return body_html, body_text


@app.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse, "description": "Service unhealthy"}},
)
async def health_check(
    queue_manager: Annotated[EmailQueueManager, Depends(get_queue_manager)],
    config: Annotated[EmailConfig, Depends(get_config)],
) -> HealthResponse | JSONResponse:
    """Check service health.

    No authentication required - used by load balancers and monitoring.
    """
    db_status = "error"
    smtp_status = "error"

    try:
        if queue_manager.health_check():
            db_status = "ok"
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")

    try:
        config.validate_smtp_config()
        smtp_status = "ok"
    except Exception:
        smtp_status = "not_configured"

    overall_status = "ok" if db_status == "ok" else "degraded"

    response = HealthResponse(
        status=overall_status,
        db=db_status,
        email_provider=smtp_status,
        version=config.SERVICE_VERSION,
    )

    if overall_status != "ok":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(mode="json"),
        )

    return response


# =============================================================================
# Entry Point
# =============================================================================
def run():
    """Run the API server."""
    import uvicorn

    # P001 fix: Use module-level _config instead of creating new instance
    logger.info(
        f"Starting {_config.SERVICE_NAME} on {_config.API_HOST}:{_config.API_PORT}"
    )
    uvicorn.run(
        "email_service.api.main:app",
        host=_config.API_HOST,
        port=_config.API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
