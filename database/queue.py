"""Email queue manager for PostgreSQL operations.

Handles all database operations for the email queue system including
enqueueing, retrieving, status updates, and retry logic.

Features:
- Connection pooling with automatic validation
- Retry decorator for transient failures
- FOR UPDATE SKIP LOCKED for concurrent processing

Author: Odiseo
Version: 2.1.0
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any, TypeVar

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from email_service.config import EmailConfig
from email_service.core.exceptions import EmailQueueError
from email_service.core.logger import get_logger
from email_service.models.email import EmailRecord, EmailStatus, EmailType

logger = get_logger(__name__)

# Type variable for generic return types
T = TypeVar("T")


# =============================================================================
# Retry Decorator
# =============================================================================
def with_db_retry(
    max_retries: int = 2,
    error_message: str = "Database operation failed",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for database operations with automatic retry on connection errors.

    Args:
        max_retries: Maximum retry attempts (default: 2).
        error_message: Base error message for failures.

    Returns:
        Decorated function with retry logic.

    Example:
        @with_db_retry(max_retries=3, error_message="Failed to fetch email")
        def _get_email(self, conn, email_id):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self: EmailQueueManager, *args: Any, **kwargs: Any) -> T:
            last_error: Exception | None = None

            for attempt in range(max_retries):
                conn = self._get_connection()
                try:
                    result = func(self, conn, *args, **kwargs)
                    return result
                except psycopg2.OperationalError as e:
                    conn.rollback()
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Connection error in {func.__name__}, "
                            f"retrying ({attempt + 1}/{max_retries})"
                        )
                        continue
                    logger.error(f"{error_message} after {max_retries} retries: {e}")
                except Exception as e:
                    conn.rollback()
                    logger.error(f"{error_message}: {e}")
                    raise EmailQueueError(f"{error_message}: {e}") from e
                finally:
                    self._return_connection(conn)

            raise EmailQueueError(f"{error_message}: {last_error}") from last_error

        return wrapper

    return decorator


def _validate_connection(conn: psycopg2.extensions.connection) -> bool:
    """Validate if a database connection is alive.

    Args:
        conn: PostgreSQL connection to validate

    Returns:
        True if connection is valid, False if dead/unusable
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        return False


class EmailQueueManager:
    """Manages email queue operations with PostgreSQL.

    Uses connection pooling for efficient database access.
    Thread-safe for multi-worker deployments.
    """

    def __init__(self, config: EmailConfig | None = None) -> None:
        """Initialize queue manager with connection pool.

        Args:
            config: Email service configuration (uses global if None).

        Raises:
            EmailQueueError: If connection pool initialization fails.
        """
        self.config = config or EmailConfig()
        self._pool: pool.SimpleConnectionPool | None = None

        try:
            self._init_pool()
            logger.info("Email Queue Manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize queue manager: {e}")
            self._cleanup_pool()
            raise EmailQueueError(f"Connection pool initialization failed: {e}") from e

    def _init_pool(self) -> None:
        """Initialize PostgreSQL connection pool with configurable size."""
        min_conn = getattr(self.config, "DB_POOL_SIZE_MIN", 1)
        max_conn = getattr(self.config, "DB_POOL_SIZE_MAX", 10)

        logger.debug(
            f"Initializing PostgreSQL connection pool (min={min_conn}, max={max_conn})..."
        )
        self._pool = pool.SimpleConnectionPool(
            minconn=min_conn,
            maxconn=max_conn,
            dsn=self.config.DATABASE_URL,
            cursor_factory=RealDictCursor,
        )

    def _cleanup_pool(self) -> None:
        """Clean up connection pool and release all connections."""
        if self._pool:
            try:
                self._pool.closeall()
                logger.debug("Connection pool closed successfully")
            except Exception as e:
                logger.warning(f"Error closing connection pool: {e}")
            finally:
                self._pool = None

    def _get_connection(self) -> psycopg2.extensions.connection:
        """Get connection from pool with automatic validation.

        Returns:
            Database connection from pool.

        Raises:
            EmailQueueError: If pool not initialized.
        """
        if not self._pool:
            raise EmailQueueError("Connection pool not initialized")

        conn = self._pool.getconn()

        if not _validate_connection(conn):
            try:
                conn.close()
            except Exception:
                pass
            self._pool.putconn(conn, close=True)
            logger.warning("Dead connection detected, retrieving fresh connection")
            conn = self._pool.getconn()

        return conn

    def _return_connection(self, conn: psycopg2.extensions.connection) -> None:
        """Return connection to pool."""
        if self._pool:
            self._pool.putconn(conn)

    def enqueue_email(
        self,
        email_type: EmailType,
        recipient_email: str,
        recipient_name: str | None,
        subject: str,
        body_html: str,
        body_text: str | None = None,
        booking_id: int | None = None,
        template_context: dict[str, Any] | None = None,
        scheduled_for: datetime | None = None,
        priority: int = 5,
    ) -> int:
        """Enqueue a new email for delivery.

        Args:
            email_type: Email category.
            recipient_email: Recipient email address.
            recipient_name: Recipient full name (optional).
            subject: Email subject line.
            body_html: HTML-formatted email body.
            body_text: Plain-text email body (optional).
            booking_id: Related booking ID (optional).
            template_context: JSON context for template rendering (optional).
            scheduled_for: When to send email (default: now).
            priority: Priority level 1-10 (default: 5).

        Returns:
            Created email record ID.

        Raises:
            EmailQueueError: If database operation fails.
        """
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    template_json = json.dumps(template_context) if template_context else None

                    logger.debug(f"Enqueueing email: type={email_type.value}, to={recipient_email}")

                    cur.execute(
                        f"""
                        SELECT {self.config.SCHEMA_NAME}.enqueue_email(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            email_type.value,
                            recipient_email,
                            recipient_name,
                            subject,
                            body_html,
                            body_text,
                            booking_id,
                            template_json,
                            scheduled_for or datetime.now(),
                            priority,
                        ),
                    )
                    result = cur.fetchone()
                    email_id: int = result["enqueue_email"] if result else 0
                    conn.commit()

                    logger.info(f"Email #{email_id} enqueued successfully")
                    return email_id

            except psycopg2.OperationalError as e:
                conn.rollback()
                if attempt < max_retries - 1:
                    logger.warning(f"Connection error, retrying ({attempt + 1}/{max_retries})")
                    continue
                logger.error(f"Failed to enqueue email after retries: {e}")
                raise EmailQueueError(f"Failed to enqueue email: {e}") from e
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to enqueue email: {e}")
                raise EmailQueueError(f"Failed to enqueue email: {e}") from e
            finally:
                self._return_connection(conn)

        raise EmailQueueError("Failed to enqueue email after all retries")

    def get_pending_emails(self, limit: int = 50) -> list[EmailRecord]:
        """Get pending emails ready for delivery.

        Uses FOR UPDATE SKIP LOCKED to prevent race conditions.

        Args:
            limit: Max emails to retrieve (default: 50, max: 1000).

        Returns:
            List of pending email records.

        Raises:
            EmailQueueError: If database operation fails.
        """
        limit = min(max(limit, 1), 1000)
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    logger.debug(f"Fetching up to {limit} pending emails...")

                    cur.execute(
                        f"SELECT * FROM {self.config.SCHEMA_NAME}.get_pending_emails(%s)",
                        (limit,),
                    )
                    rows = cur.fetchall()
                    conn.commit()

                    if not rows:
                        logger.debug("No pending emails in queue")
                        return []

                    email_records = []
                    for row in rows:
                        row_dict = dict(row)
                        template_context_raw = row_dict.get("template_context")
                        if template_context_raw and isinstance(template_context_raw, str):
                            row_dict["template_context"] = json.loads(template_context_raw)

                        # Set default timestamps if not present in database row
                        if "created_at" not in row_dict or row_dict["created_at"] is None:
                            row_dict["created_at"] = datetime.now()
                        if "updated_at" not in row_dict or row_dict["updated_at"] is None:
                            row_dict["updated_at"] = datetime.now()

                        email_records.append(EmailRecord(**row_dict))

                    logger.info(f"Retrieved {len(email_records)} pending emails")
                    return email_records

            except psycopg2.OperationalError as e:
                conn.rollback()
                if attempt < max_retries - 1:
                    logger.warning(f"Connection error, retrying ({attempt + 1}/{max_retries})")
                    continue
                logger.error(f"Failed to get pending emails after retries: {e}")
                raise EmailQueueError(f"Failed to retrieve pending emails: {e}") from e
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to get pending emails: {e}")
                raise EmailQueueError(f"Failed to retrieve pending emails: {e}") from e
            finally:
                self._return_connection(conn)

        raise EmailQueueError("Failed to get pending emails after all retries")

    def update_email_status(
        self,
        email_id: int,
        status: EmailStatus,
        error: str | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        """Update email delivery status.

        Args:
            email_id: Email ID to update.
            status: New status (sent, failed, processing).
            error: Error message if failed (optional).
            sent_at: Delivery timestamp if sent (optional).

        Raises:
            EmailQueueError: If database operation fails.
        """
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    logger.debug(f"Updating email #{email_id} status to {status.value}")

                    cur.execute(
                        f"""
                        SELECT {self.config.SCHEMA_NAME}.update_email_status(
                            %s, %s, %s, %s
                        )
                        """,
                        (email_id, status.value, error, sent_at),
                    )
                    conn.commit()

                    logger.info(f"Email #{email_id} status updated to {status.value}")
                    return

            except psycopg2.OperationalError as e:
                conn.rollback()
                if attempt < max_retries - 1:
                    logger.warning(f"Connection error, retrying ({attempt + 1}/{max_retries})")
                    continue
                logger.error(f"Failed to update email #{email_id} status: {e}")
                raise EmailQueueError(f"Failed to update email status: {e}") from e
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to update email #{email_id} status: {e}")
                raise EmailQueueError(f"Failed to update email status: {e}") from e
            finally:
                self._return_connection(conn)

    def retry_email(self, email_id: int, error: str, backoff_seconds: int = 300) -> None:
        """Retry failed email with exponential backoff.

        Args:
            email_id: Email ID to retry.
            error: Error message from failed attempt.
            backoff_seconds: Initial backoff duration (default: 300s).

        Raises:
            EmailQueueError: If database operation fails.
        """
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    logger.debug(f"Scheduling retry for email #{email_id}, backoff={backoff_seconds}s")

                    cur.execute(
                        f"""
                        SELECT {self.config.SCHEMA_NAME}.retry_email(%s, %s, %s)
                        """,
                        (email_id, error, backoff_seconds),
                    )
                    conn.commit()

                    logger.info(f"Email #{email_id} scheduled for retry")
                    return

            except psycopg2.OperationalError as e:
                conn.rollback()
                if attempt < max_retries - 1:
                    logger.warning(f"Connection error, retrying ({attempt + 1}/{max_retries})")
                    continue
                logger.error(f"Failed to retry email #{email_id}: {e}")
                raise EmailQueueError(f"Failed to retry email: {e}") from e
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to retry email #{email_id}: {e}")
                raise EmailQueueError(f"Failed to retry email: {e}") from e
            finally:
                self._return_connection(conn)

    def get_email_by_id(self, email_id: int) -> EmailRecord | None:
        """Get email record by ID.

        Args:
            email_id: Email ID to retrieve.

        Returns:
            Email record or None if not found.

        Raises:
            EmailQueueError: If database operation fails.
        """
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT * FROM {self.config.SCHEMA_NAME}.email_queue
                        WHERE id = %s
                        """,
                        (email_id,),
                    )
                    row = cur.fetchone()

                    if not row:
                        logger.debug(f"Email #{email_id} not found")
                        return None

                    row_dict = dict(row)
                    template_context_raw = row_dict.get("template_context")
                    if template_context_raw and isinstance(template_context_raw, str):
                        row_dict["template_context"] = json.loads(template_context_raw)

                    return EmailRecord(**row_dict)

            except psycopg2.OperationalError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Connection error, retrying ({attempt + 1}/{max_retries})")
                    continue
                logger.error(f"Failed to get email #{email_id}: {e}")
                raise EmailQueueError(f"Failed to retrieve email: {e}") from e
            except Exception as e:
                logger.error(f"Failed to get email #{email_id}: {e}")
                raise EmailQueueError(f"Failed to retrieve email: {e}") from e
            finally:
                self._return_connection(conn)

        return None

    def cleanup_old_emails(self, days_to_keep: int = 90) -> int:
        """Cleanup old sent/failed emails.

        Args:
            days_to_keep: Keep emails from last N days (default: 90).

        Returns:
            Number of deleted emails.

        Raises:
            EmailQueueError: If database operation fails.
        """
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    logger.info(f"Cleaning up emails older than {days_to_keep} days...")

                    cur.execute(
                        f"SELECT {self.config.SCHEMA_NAME}.cleanup_old_emails(%s)",
                        (days_to_keep,),
                    )
                    result = cur.fetchone()
                    deleted_count: int = result["cleanup_old_emails"] if result else 0
                    conn.commit()

                    logger.info(f"Deleted {deleted_count} old emails")
                    return deleted_count

            except psycopg2.OperationalError as e:
                conn.rollback()
                if attempt < max_retries - 1:
                    logger.warning(f"Connection error, retrying ({attempt + 1}/{max_retries})")
                    continue
                logger.error(f"Failed to cleanup old emails: {e}")
                raise EmailQueueError(f"Failed to cleanup emails: {e}") from e
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to cleanup old emails: {e}")
                raise EmailQueueError(f"Failed to cleanup emails: {e}") from e
            finally:
                self._return_connection(conn)

        return 0

    def get_queue_stats(self) -> dict[str, int]:
        """Get email queue statistics by status.

        Returns:
            Dictionary mapping status names to counts.

        Raises:
            EmailQueueError: If database operation fails.
        """
        max_retries = 2

        for attempt in range(max_retries):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT status, COUNT(*) as count
                        FROM {self.config.SCHEMA_NAME}.email_queue
                        GROUP BY status
                        """
                    )
                    rows = cur.fetchall()

                return {row["status"]: row["count"] for row in rows}

            except psycopg2.OperationalError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Connection error, retrying ({attempt + 1}/{max_retries})"
                    )
                    continue
                logger.error(f"Failed to get queue stats: {e}")
                raise EmailQueueError(f"Failed to get queue stats: {e}") from e
            except Exception as e:
                logger.error(f"Failed to get queue stats: {e}")
                raise EmailQueueError(f"Failed to get queue stats: {e}") from e
            finally:
                self._return_connection(conn)

        return {}

    def health_check(self) -> bool:
        """Check database connectivity.

        Returns:
            True if database is accessible, False otherwise.
        """
        try:
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                return True
            finally:
                self._return_connection(conn)
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def close(self) -> None:
        """Close all connections in pool."""
        if self._pool:
            logger.info("Closing database connection pool...")
            self._cleanup_pool()
            logger.info("Connection pool closed")
