"""Email Microservice API.

FastAPI application providing endpoints for email operations:
- POST /emails: Send an email (queued for delivery)
- GET /queue/status: Get queue statistics
- GET /health: Service health check
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

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

logger = get_logger(__name__)

# Global instances
config: EmailConfig | None = None
queue_manager: EmailQueueManager | None = None
app: FastAPI | None = None


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    global config
    config = EmailConfig()

    application = FastAPI(
        title=config.SERVICE_NAME,
        description="Production-ready email sending microservice with queue management",
        version=config.SERVICE_VERSION,
    )

    return application


app = create_app()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global config, queue_manager

    setup_logging(
        log_level=config.LOG_LEVEL,
        enable_file=config.LOG_TO_FILE,
        settings=config,
    )

    try:
        queue_manager = EmailQueueManager(config)
        logger.info(f"Database connected: {config.SCHEMA_NAME}.email_queue")
    except Exception as e:
        logger.error(f"Failed to start API: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global queue_manager, config

    logger.info(f"Shutting down {config.SERVICE_NAME}...")
    if queue_manager:
        queue_manager.close()
    logger.info(f"{config.SERVICE_NAME} stopped")


@app.post(
    "/emails",
    response_model=EmailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
)
async def send_email(request: EmailRequest) -> EmailResponse:
    """Queue an email for delivery."""
    global queue_manager

    if not queue_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )

    # Map template_id to EmailType
    template_type_map = {
        "otp_verification": EmailType.OTP_VERIFICATION,
        "booking_created": EmailType.BOOKING_CREATED,
        "booking_cancelled": EmailType.BOOKING_CANCELLED,
        "booking_rescheduled": EmailType.BOOKING_RESCHEDULED,
        "reminder_24h": EmailType.REMINDER_24H,
        "reminder_1h": EmailType.REMINDER_1H,
    }

    try:
        message_id = request.client_message_id or str(uuid.uuid4())

        # Determine email type based on template_id
        email_type = EmailType.TRANSACTIONAL
        if request.template_id:
            email_type = template_type_map.get(request.template_id, EmailType.TRANSACTIONAL)

        for recipient in request.to:
            queue_manager.enqueue_email(
                email_type=email_type,
                recipient_email=recipient,
                recipient_name=request.template_vars.get("recipient_name") if request.template_vars else None,
                subject=request.subject,
                body_html=request.body,
                template_context=request.template_vars if request.template_id else None,
            )

        logger.info(f"Email queued: {message_id} to {len(request.to)} recipients (type={email_type.value})")

        return EmailResponse(
            status="accepted",
            queued=True,
            message_id=message_id,
            detail="Email stored in queue",
        )

    except Exception as e:
        logger.error(f"Failed to queue email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get(
    "/queue/status",
    response_model=QueueStatusResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
)
async def get_queue_status() -> QueueStatusResponse:
    """Get email queue statistics."""
    global queue_manager, config

    if not queue_manager or not config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )

    try:
        conn = queue_manager._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT status, COUNT(*) as count
                    FROM {config.SCHEMA_NAME}.email_queue
                    GROUP BY status
                    """
                )
                rows = cur.fetchall()

            counts = {row["status"]: row["count"] for row in rows}

            return QueueStatusResponse(
                pending=counts.get(EmailStatus.PENDING.value, 0),
                scheduled=counts.get(EmailStatus.SCHEDULED.value, 0),
                processing=counts.get(EmailStatus.PROCESSING.value, 0),
                sent=counts.get(EmailStatus.SENT.value, 0),
                failed=counts.get(EmailStatus.FAILED.value, 0),
            )

        finally:
            queue_manager._return_connection(conn)

    except Exception as e:
        logger.error(f"Failed to get queue status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse, "description": "Service unhealthy"}},
)
async def health_check() -> HealthResponse:
    """Check service health."""
    global queue_manager, config

    db_status = "error"
    smtp_status = "error"

    if queue_manager:
        try:
            conn = queue_manager._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            queue_manager._return_connection(conn)
            db_status = "ok"
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")

    if config:
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
