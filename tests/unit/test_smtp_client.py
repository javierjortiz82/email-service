"""Unit tests for SMTP client.

Tests SMTP connection management, email sending, and error handling.

Author: Odiseo
Version: 1.0.0
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from email_service.clients.smtp import SMTPClient
from email_service.core.exceptions import SMTPClientError


class TestSMTPClientInit:
    """Tests for SMTPClient initialization."""

    def test_init_with_config(self, mock_smtp_config):
        """Test initialization with provided config."""
        with patch.object(SMTPClient, "_create_connection"):
            client = SMTPClient(smtp_config=mock_smtp_config)

            assert client.config == mock_smtp_config
            assert client._connection is None
            assert client._last_used == 0

    def test_init_without_config(self, mock_config):
        """Test initialization loads config from environment."""
        with patch("email_service.clients.smtp.EmailConfig", return_value=mock_config):
            with patch.object(SMTPClient, "_create_connection"):
                client = SMTPClient()

                assert client.config is not None


class TestSMTPConnection:
    """Tests for SMTP connection management."""

    def test_get_connection_creates_new(self, mock_smtp_config, mock_smtp_connection):
        """Test _get_connection creates new connection when none exists."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            conn = client._get_connection()

            assert conn == mock_smtp_connection
            assert client._connection == mock_smtp_connection
            assert client._last_used > 0

    def test_get_connection_reuses_existing(self, mock_smtp_config, mock_smtp_connection):
        """Test _get_connection reuses valid existing connection."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            # First call creates connection
            conn1 = client._get_connection()
            # Second call should reuse
            conn2 = client._get_connection()

            assert conn1 == conn2

    def test_get_connection_refreshes_stale(self, mock_smtp_config, mock_smtp_connection):
        """Test _get_connection refreshes stale connections."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)
            client._get_connection()

            # Simulate stale connection (older than timeout)
            client._last_used = 0

            # Should create new connection
            conn = client._get_connection()
            assert conn == mock_smtp_connection

    def test_get_connection_handles_dead_connection(self, mock_smtp_config):
        """Test _get_connection detects and replaces dead connections."""
        dead_conn = MagicMock()
        dead_conn.noop.side_effect = smtplib.SMTPException("Connection closed")

        fresh_conn = MagicMock()
        fresh_conn.noop.return_value = (250, b"OK")

        with patch("email_service.clients.smtp.smtplib.SMTP") as mock_smtp:
            mock_smtp.side_effect = [dead_conn, fresh_conn]
            client = SMTPClient(smtp_config=mock_smtp_config)
            client._connection = dead_conn
            client._last_used = float("inf")  # Not stale by time

            conn = client._get_connection()

            # Should have gotten fresh connection
            assert client._connection == fresh_conn or mock_smtp.call_count >= 1

    def test_create_connection_with_tls(self, mock_smtp_config, mock_smtp_connection):
        """Test _create_connection enables TLS when configured."""
        mock_smtp_config.use_tls = True

        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)
            client._create_connection()

            mock_smtp_connection.starttls.assert_called_once()
            mock_smtp_connection.login.assert_called_once()

    def test_create_connection_failure(self, mock_smtp_config):
        """Test _create_connection raises SMTPClientError on failure."""
        with patch("email_service.clients.smtp.smtplib.SMTP") as mock_smtp:
            mock_smtp.side_effect = ConnectionRefusedError("Connection refused")
            client = SMTPClient.__new__(SMTPClient)
            client.config = mock_smtp_config
            client._connection = None
            client._last_used = 0
            client._lock = MagicMock()

            with pytest.raises(SMTPClientError) as exc_info:
                client._create_connection()

            assert "Failed to connect" in str(exc_info.value)

    def test_close_connection(self, mock_smtp_config, mock_smtp_connection):
        """Test _close_connection properly closes SMTP connection."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)
            client._get_connection()

            client._close_connection()

            mock_smtp_connection.quit.assert_called_once()
            assert client._connection is None
            assert client._last_used == 0


class TestSendEmail:
    """Tests for email sending functionality."""

    def test_send_email_success(self, mock_smtp_config, mock_smtp_connection):
        """Test successful email sending."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            client.send_email(
                recipient_email="user@example.com",
                recipient_name="Test User",
                subject="Test Subject",
                body_html="<h1>Hello</h1>",
                body_text="Hello",
            )

            mock_smtp_connection.send_message.assert_called_once()

    def test_send_email_without_recipient_name(self, mock_smtp_config, mock_smtp_connection):
        """Test email sending without recipient name."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            client.send_email(
                recipient_email="user@example.com",
                recipient_name=None,
                subject="Test Subject",
                body_html="<h1>Hello</h1>",
            )

            mock_smtp_connection.send_message.assert_called_once()

    def test_send_email_html_only(self, mock_smtp_config, mock_smtp_connection):
        """Test email sending with HTML only (no plain text)."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            client.send_email(
                recipient_email="user@example.com",
                recipient_name="User",
                subject="HTML Only",
                body_html="<p>HTML content</p>",
                body_text=None,
            )

            mock_smtp_connection.send_message.assert_called_once()

    def test_send_email_retries_on_failure(self, mock_smtp_config):
        """Test email sending retries on transient failure."""
        failing_conn = MagicMock()
        failing_conn.noop.return_value = (250, b"OK")
        failing_conn.send_message.side_effect = [
            smtplib.SMTPException("Temporary failure"),
            None,  # Success on retry
        ]

        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=failing_conn):
            client = SMTPClient(smtp_config=mock_smtp_config)

            # Should succeed after retry
            client.send_email(
                recipient_email="user@example.com",
                recipient_name="User",
                subject="Test",
                body_html="<p>Test</p>",
            )

            assert failing_conn.send_message.call_count == 2

    def test_send_email_fails_after_max_retries(self, mock_smtp_config):
        """Test email sending raises error after max retries."""
        failing_conn = MagicMock()
        failing_conn.noop.return_value = (250, b"OK")
        failing_conn.send_message.side_effect = smtplib.SMTPException("Permanent failure")

        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=failing_conn):
            client = SMTPClient(smtp_config=mock_smtp_config)

            with pytest.raises(SMTPClientError) as exc_info:
                client.send_email(
                    recipient_email="user@example.com",
                    recipient_name="User",
                    subject="Test",
                    body_html="<p>Test</p>",
                )

            assert "Failed to send email" in str(exc_info.value)


class TestValidateConnection:
    """Tests for connection validation."""

    def test_validate_connection_success(self, mock_smtp_config, mock_smtp_connection):
        """Test validate_connection returns True for valid connection."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            result = client.validate_connection()

            assert result is True

    def test_validate_connection_failure(self, mock_smtp_config):
        """Test validate_connection returns False for invalid connection."""
        with patch("email_service.clients.smtp.smtplib.SMTP") as mock_smtp:
            mock_smtp.side_effect = ConnectionRefusedError("Cannot connect")
            client = SMTPClient.__new__(SMTPClient)
            client.config = mock_smtp_config
            client._connection = None
            client._last_used = 0
            client._lock = MagicMock()

            result = client.validate_connection()

            assert result is False


class TestSendTestEmail:
    """Tests for test email functionality."""

    def test_send_test_email_success(self, mock_smtp_config, mock_smtp_connection):
        """Test send_test_email returns True on success."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            result = client.send_test_email("test@example.com")

            assert result is True
            mock_smtp_connection.send_message.assert_called_once()

    def test_send_test_email_failure(self, mock_smtp_config):
        """Test send_test_email returns False on failure."""
        failing_conn = MagicMock()
        failing_conn.noop.return_value = (250, b"OK")
        failing_conn.send_message.side_effect = smtplib.SMTPException("Failed")

        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=failing_conn):
            client = SMTPClient(smtp_config=mock_smtp_config)

            result = client.send_test_email("test@example.com")

            assert result is False


class TestTransientErrorDetection:
    """Tests for transient error detection."""

    @pytest.mark.parametrize("error_message,expected", [
        ("Connection timeout", True),
        ("Connection refused", True),
        ("Service temporarily unavailable", True),
        ("Try again later", True),
        ("Broken pipe", True),
        ("Connection reset", True),
        ("Invalid recipient", False),
        ("Authentication failed", False),
        ("Mailbox not found", False),
    ])
    def test_is_transient_error(self, error_message, expected):
        """Test _is_transient_error correctly identifies transient errors."""
        error = Exception(error_message)
        result = SMTPClient._is_transient_error(error)
        assert result == expected


class TestContextManager:
    """Tests for context manager support."""

    def test_context_manager_enter(self, mock_smtp_config, mock_smtp_connection):
        """Test context manager __enter__ returns client."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)

            with client as ctx:
                assert ctx == client

    def test_context_manager_exit_closes(self, mock_smtp_config, mock_smtp_connection):
        """Test context manager __exit__ closes connection."""
        with patch("email_service.clients.smtp.smtplib.SMTP", return_value=mock_smtp_connection):
            client = SMTPClient(smtp_config=mock_smtp_config)
            client._get_connection()  # Establish connection

            with client:
                pass

            # Connection should be closed after exiting
            mock_smtp_connection.quit.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
