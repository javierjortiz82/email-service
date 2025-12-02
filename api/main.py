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
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated

from email_service.api.schemas import (
    EmailRequest,
    EmailResponse,
    ErrorResponse,
    HealthResponse,
    QueueStatusResponse,
)
from email_service.config import EmailConfig
from email_service.core.logger import get_logger, setup_logging
from email_service.database.queue import EmailQueueManager
from email_service.models.email import EmailStatus, EmailType
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
    _requests: dict = field(default_factory=lambda: defaultdict(list))
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
            recent_second = [t for t in self._requests.get(client_id, []) if now - t < 1]
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
            client_ip = getattr(request.client, "host", "unknown") if request.client else "unknown"

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

    if api_key != configured_key:
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

    cfg = EmailConfig()
    logger.info(f"Starting {cfg.SERVICE_NAME} on {cfg.API_HOST}:{cfg.API_PORT}")
    uvicorn.run(
        "email_service.api.main:app",
        host=cfg.API_HOST,
        port=cfg.API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
