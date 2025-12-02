"""Email worker - Queue processor and email delivery daemon.

Continuously polls the email queue and delivers emails via SMTP.
Handles template rendering, retry logic, and graceful shutdown.

Version: 2.0.0
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime
from typing import Any

from email_service.clients.smtp import SMTPClient
from email_service.config import EmailConfig
from email_service.core.exceptions import EmailServiceError
from email_service.core.logger import get_logger, setup_logging, log_context
from email_service.database.queue import EmailQueueManager
from email_service.models.email import EmailRecord, EmailStatus, EmailType
from email_service.templates.renderer import TemplateRenderer

logger = get_logger(__name__)


class EmailWorker:
    """Email queue processor daemon.

    Continuously polls the queue and delivers emails via SMTP.
    Handles graceful shutdown on SIGTERM/SIGINT with proper cleanup.
    """

    def __init__(self) -> None:
        """Initialize email worker components.

        Raises:
            EmailServiceError: If initialization fails.
        """
        self.config = EmailConfig()

        setup_logging(
            log_level=self.config.LOG_LEVEL,
            file_level="DEBUG",
            console_level=self.config.LOG_LEVEL,
            enable_file=self.config.LOG_TO_FILE,
            settings=self.config,
        )

        try:
            logger.debug("Email configuration loaded")

            self.config.validate_smtp_config()
            logger.debug("SMTP configuration validated")

            self.queue_manager = EmailQueueManager(self.config)
            logger.debug("Queue manager initialized")

            self.smtp_client = SMTPClient()
            logger.debug("SMTP client initialized")

            if not self.smtp_client.validate_connection():
                raise EmailServiceError(
                    "SMTP connection validation failed. Check SMTP configuration."
                )
            logger.debug("SMTP connection validated successfully")

            self.template_renderer = TemplateRenderer()
            logger.debug("Template renderer initialized")

            self.running = True
            self.processed_count = 0
            self.failed_count = 0

            signal.signal(signal.SIGTERM, self._handle_shutdown)
            signal.signal(signal.SIGINT, self._handle_shutdown)

            logger.info("Email Worker initialized successfully")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Failed to initialize worker: {e}", exc_info=True)
            raise EmailServiceError(f"Worker initialization failed: {e}") from e

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Received shutdown signal ({signum}). Stopping gracefully...")
        self.running = False

    async def run(self) -> None:
        """Main worker loop - polls queue and processes emails."""
        logger.info("Starting email worker loop...")
        logger.info(
            f"Worker Configuration: "
            f"poll_interval={self.config.EMAIL_WORKER_POLL_INTERVAL}s | "
            f"batch_size={self.config.EMAIL_WORKER_BATCH_SIZE} | "
            f"max_retries={self.config.EMAIL_RETRY_MAX_ATTEMPTS} | "
            f"retry_backoff={self.config.EMAIL_RETRY_BACKOFF_SECONDS}s"
        )

        cycle_count = 0
        while self.running:
            cycle_count += 1
            try:
                await self._process_batch()
            except Exception:
                logger.error(f"Cycle #{cycle_count}: Unexpected error in worker loop", exc_info=True)

            await asyncio.sleep(self.config.EMAIL_WORKER_POLL_INTERVAL)

        logger.info("Shutting down email worker...")
        logger.info("=" * 80)
        self._print_stats()
        self.queue_manager.close()
        logger.info("Email worker stopped cleanly")
        logger.info("=" * 80)

    async def _process_batch(self) -> None:
        """Process a batch of pending emails from queue."""
        try:
            pending_emails = self.queue_manager.get_pending_emails(
                limit=self.config.EMAIL_WORKER_BATCH_SIZE
            )

            if not pending_emails:
                logger.debug("No pending emails in queue")
                return

            logger.info(f"Processing {len(pending_emails)} pending emails...")

            for email in pending_emails:
                try:
                    await self._process_email(email)
                    self.processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing email {email.id}: {e}", exc_info=True)
                    self.failed_count += 1

        except Exception as e:
            logger.error(f"Batch processing error: {e}", exc_info=True)

    async def _process_email(self, email: EmailRecord) -> None:
        """Process a single email record."""
        ctx = log_context(
            logger,
            "process_email",
            email_id=email.id,
            recipient=email.recipient_email,
            type=email.type.value,
        )

        try:
            logger.info(f"Starting: {ctx}")

            self.queue_manager.update_email_status(email.id, EmailStatus.PROCESSING)
            logger.debug(f"Status marked PROCESSING: {ctx}")

            body_html, body_text = self._prepare_email_content(email)

            self.smtp_client.send_email(
                recipient_email=email.recipient_email,
                recipient_name=email.recipient_name,
                subject=email.subject,
                body_html=body_html,
                body_text=body_text,
            )

            logger.debug(f"SMTP delivery OK: {ctx}")

            self.queue_manager.update_email_status(
                email.id, EmailStatus.SENT, sent_at=datetime.now()
            )

            logger.info(f"COMPLETED: {ctx}")

        except Exception as e:
            logger.error(f"FAILED: {ctx} | Error: {str(e)}", exc_info=True)
            self._handle_send_failure(email, str(e))
            raise

    def _prepare_email_content(self, email: EmailRecord) -> tuple[str, str | None]:
        """Prepare email content (render if needed or use pre-rendered)."""
        if email.template_context:
            logger.debug(f"Rendering template for email type: {email.type}")

            body_html = self.template_renderer.render_html(
                EmailType(email.type), email.template_context
            )
            body_text = self.template_renderer.render_text(
                EmailType(email.type), email.template_context
            )

            logger.debug(f"Template rendered - HTML: {len(body_html)} bytes")
        else:
            logger.debug(f"Using pre-rendered content - HTML: {len(email.body_html)} bytes")

            body_html = email.body_html
            body_text = email.body_text

            if not body_html.strip() and (not body_text or not body_text.strip()):
                logger.warning(f"Email #{email.id} has no content!")

        return body_html, body_text

    def _handle_send_failure(self, email: EmailRecord, error: str) -> None:
        """Handle email send failure with retry logic."""
        ctx = log_context(
            logger,
            "handle_failure",
            email_id=email.id,
            recipient=email.recipient_email,
        )

        if email.retry_count < email.max_retries:
            backoff = self.config.EMAIL_RETRY_BACKOFF_SECONDS
            self.queue_manager.retry_email(
                email.id,
                error=error,
                backoff_seconds=backoff,
            )
            logger.warning(
                f"SCHEDULED RETRY: {ctx} | "
                f"attempt {email.retry_count + 1}/{email.max_retries} | "
                f"backoff_secs={backoff}"
            )
        else:
            self.queue_manager.update_email_status(
                email.id, EmailStatus.FAILED, error=error
            )
            logger.critical(
                f"PERMANENTLY FAILED: {ctx} | "
                f"max_retries_exceeded={email.max_retries} | "
                f"error={error[:100]}"
            )

    def _print_stats(self) -> None:
        """Print worker statistics on shutdown."""
        total = self.processed_count + self.failed_count
        success_rate = (self.processed_count / total * 100) if total > 0 else 0

        logger.info("Email Worker Statistics:")
        logger.info(f"   Total processed: {total}")
        logger.info(f"   Successfully sent: {self.processed_count}")
        logger.info(f"   Failed: {self.failed_count}")
        logger.info(f"   Success rate: {success_rate:.1f}%")


async def main() -> None:
    """Main entry point for worker process."""
    try:
        worker = EmailWorker()
        await worker.run()
    except EmailServiceError as e:
        logger.error(f"Email Service Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
