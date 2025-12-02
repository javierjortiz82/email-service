"""Unit tests for EmailQueueManager.

Tests database operations, connection pooling, and retry logic.

Author: Odiseo
Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from email_service.core.exceptions import EmailQueueError
from email_service.database.queue import (
    EmailQueueManager,
    _validate_connection,
    with_db_retry,
)
from email_service.models.email import EmailStatus, EmailType


class TestValidateConnection:
    """Tests for connection validation function."""

    def test_validate_connection_alive(self):
        """Test validation with a healthy connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_cursor.execute.return_value = None
        mock_cursor.fetchone.return_value = (1,)

        result = _validate_connection(mock_conn)
        assert result is True

    def test_validate_connection_dead(self):
        """Test validation detects dead connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("server closed")

        result = _validate_connection(mock_conn)
        assert result is False

    def test_validate_connection_interface_error(self):
        """Test validation detects interface errors."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.InterfaceError("connection already closed")

        result = _validate_connection(mock_conn)
        assert result is False


class TestWithDbRetryDecorator:
    """Tests for the database retry decorator."""

    def test_decorator_success_first_try(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test decorator returns result on first successful try."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = {"result": 42}

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                @with_db_retry(max_retries=2, error_message="Test failed")
                def test_func(self, conn):
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        return cur.fetchone()

                result = test_func(manager)
                assert result == {"result": 42}

    def test_decorator_retries_on_operational_error(self, mock_config, mock_connection_pool):
        """Test decorator retries on OperationalError."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor

        # First call fails, second succeeds
        call_count = [0]

        def side_effect(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                raise psycopg2.OperationalError("Connection lost")
            return None

        mock_cursor.execute.side_effect = side_effect
        mock_cursor.fetchone.return_value = {"result": "success"}
        mock_connection_pool.getconn.return_value = mock_conn

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                @with_db_retry(max_retries=2, error_message="Test failed")
                def test_func(self, conn):
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        return cur.fetchone()

                result = test_func(manager)
                assert result == {"result": "success"}
                assert call_count[0] == 2

    def test_decorator_raises_after_max_retries(self, mock_config, mock_connection_pool):
        """Test decorator raises error after max retries exceeded."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("Connection lost")
        mock_connection_pool.getconn.return_value = mock_conn

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                @with_db_retry(max_retries=2, error_message="Test operation failed")
                def test_func(self, conn):
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")

                with pytest.raises(EmailQueueError) as exc_info:
                    test_func(manager)

                assert "Test operation failed" in str(exc_info.value)

    def test_decorator_raises_immediately_on_other_errors(self, mock_config, mock_connection_pool):
        """Test decorator raises immediately on non-retryable errors."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = ValueError("Invalid value")
        mock_connection_pool.getconn.return_value = mock_conn

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                @with_db_retry(max_retries=3, error_message="Value error")
                def test_func(self, conn):
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")

                with pytest.raises(EmailQueueError):
                    test_func(manager)

                # Should fail immediately without retries
                assert mock_cursor.execute.call_count == 1


class TestEmailQueueManagerInit:
    """Tests for EmailQueueManager initialization."""

    def test_init_creates_pool(self, mock_config, mock_connection_pool):
        """Test initialization creates connection pool."""
        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            manager = EmailQueueManager(config=mock_config)

            assert manager._pool is not None
            assert manager.config == mock_config

    def test_init_without_config(self, mock_config):
        """Test initialization loads config when not provided."""
        with patch("email_service.database.queue.EmailConfig", return_value=mock_config):
            with patch("email_service.database.queue.pool.SimpleConnectionPool") as mock_pool:
                mock_pool.return_value = MagicMock()
                manager = EmailQueueManager()

                assert manager.config is not None

    def test_init_fails_gracefully(self, mock_config):
        """Test initialization handles pool creation failure."""
        with patch("email_service.database.queue.pool.SimpleConnectionPool") as mock_pool:
            mock_pool.side_effect = Exception("Cannot connect to database")

            with pytest.raises(EmailQueueError) as exc_info:
                EmailQueueManager(config=mock_config)

            assert "Connection pool initialization failed" in str(exc_info.value)


class TestEmailQueueManagerGetConnection:
    """Tests for connection pool operations."""

    def test_get_connection_from_pool(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test getting connection from pool."""
        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                conn = manager._get_connection()

                assert conn == mock_db_connection
                mock_connection_pool.getconn.assert_called_once()

    def test_get_connection_replaces_dead(self, mock_config, mock_connection_pool):
        """Test getting connection replaces dead connections."""
        dead_conn = MagicMock()
        fresh_conn = MagicMock()
        mock_connection_pool.getconn.side_effect = [dead_conn, fresh_conn]

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", side_effect=[False, True]):
                manager = EmailQueueManager(config=mock_config)

                conn = manager._get_connection()

                assert conn == fresh_conn
                assert mock_connection_pool.getconn.call_count == 2

    def test_get_connection_raises_without_pool(self, mock_config, mock_connection_pool):
        """Test getting connection raises when pool not initialized."""
        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            manager = EmailQueueManager(config=mock_config)
            manager._pool = None

            with pytest.raises(EmailQueueError) as exc_info:
                manager._get_connection()

            assert "Connection pool not initialized" in str(exc_info.value)

    def test_return_connection_to_pool(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test returning connection to pool."""
        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)
                conn = manager._get_connection()

                manager._return_connection(conn)

                mock_connection_pool.putconn.assert_called_once_with(conn)


class TestEnqueueEmail:
    """Tests for email enqueueing."""

    def test_enqueue_email_success(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test successful email enqueueing."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = {"enqueue_email": 123}

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                email_id = manager.enqueue_email(
                    email_type=EmailType.TRANSACTIONAL,
                    recipient_email="user@example.com",
                    recipient_name="Test User",
                    subject="Test Subject",
                    body_html="<p>Test body</p>",
                )

                assert email_id == 123
                mock_cursor.execute.assert_called_once()
                mock_db_connection.commit.assert_called_once()

    def test_enqueue_email_with_template_context(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test enqueueing email with template context."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = {"enqueue_email": 124}

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                email_id = manager.enqueue_email(
                    email_type=EmailType.BOOKING_CREATED,
                    recipient_email="user@example.com",
                    recipient_name="Test User",
                    subject="Booking Confirmation",
                    body_html="<p>Booking details</p>",
                    template_context={"booking_id": 456, "date": "2025-01-15"},
                )

                assert email_id == 124


class TestGetPendingEmails:
    """Tests for retrieving pending emails."""

    def test_get_pending_emails_success(self, mock_config, mock_connection_pool, mock_db_connection, sample_email_record):
        """Test successful retrieval of pending emails."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchall.return_value = [sample_email_record]

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                emails = manager.get_pending_emails(limit=10)

                assert len(emails) == 1
                assert emails[0].recipient_email == "user@example.com"

    def test_get_pending_emails_empty(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test retrieval when no pending emails."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchall.return_value = []

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                emails = manager.get_pending_emails()

                assert emails == []

    def test_get_pending_emails_limit_clamped(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test limit is clamped to valid range."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchall.return_value = []

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                # Test with too high limit
                manager.get_pending_emails(limit=5000)
                call_args = mock_cursor.execute.call_args
                assert call_args[0][1][0] <= 1000


class TestUpdateEmailStatus:
    """Tests for email status updates."""

    def test_update_status_to_sent(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test updating email status to sent."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                manager.update_email_status(
                    email_id=123,
                    status=EmailStatus.SENT,
                    sent_at=datetime.now(),
                )

                mock_cursor.execute.assert_called_once()
                mock_db_connection.commit.assert_called_once()

    def test_update_status_to_failed(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test updating email status to failed with error."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                manager.update_email_status(
                    email_id=123,
                    status=EmailStatus.FAILED,
                    error="SMTP connection timeout",
                )

                mock_cursor.execute.assert_called_once()


class TestRetryEmail:
    """Tests for email retry functionality."""

    def test_retry_email(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test scheduling email for retry."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                manager.retry_email(
                    email_id=123,
                    error="Temporary failure",
                    backoff_seconds=600,
                )

                mock_cursor.execute.assert_called_once()


class TestGetQueueStats:
    """Tests for queue statistics."""

    def test_get_queue_stats(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test getting queue statistics."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchall.return_value = [
            {"status": "pending", "count": 10},
            {"status": "sent", "count": 100},
            {"status": "failed", "count": 5},
        ]

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                stats = manager.get_queue_stats()

                assert stats["pending"] == 10
                assert stats["sent"] == 100
                assert stats["failed"] == 5


class TestHealthCheck:
    """Tests for health check functionality."""

    def test_health_check_success(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test health check returns True when database is accessible."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = (1,)

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                result = manager.health_check()

                assert result is True

    def test_health_check_failure(self, mock_config, mock_connection_pool, mock_db_connection):
        """Test health check returns False when database is inaccessible."""
        mock_cursor = mock_db_connection.cursor.return_value.__enter__.return_value
        mock_cursor.execute.side_effect = Exception("Connection failed")

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            with patch("email_service.database.queue._validate_connection", return_value=True):
                manager = EmailQueueManager(config=mock_config)

                result = manager.health_check()

                assert result is False


class TestClose:
    """Tests for connection pool cleanup."""

    def test_close_pool(self, mock_config, mock_connection_pool):
        """Test close properly closes connection pool."""
        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            manager = EmailQueueManager(config=mock_config)

            manager.close()

            mock_connection_pool.closeall.assert_called_once()
            assert manager._pool is None

    def test_close_handles_errors(self, mock_config, mock_connection_pool):
        """Test close handles errors gracefully."""
        mock_connection_pool.closeall.side_effect = Exception("Close error")

        with patch("email_service.database.queue.pool.SimpleConnectionPool", return_value=mock_connection_pool):
            manager = EmailQueueManager(config=mock_config)

            # Should not raise exception
            manager.close()

            assert manager._pool is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
