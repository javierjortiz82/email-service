"""SMTP client for email delivery.

Provides email sending via SMTP with support for Gmail, SendGrid, AWS SES,
and compatible SMTP servers. Features connection reuse for better performance.

Features:
- Connection reuse with automatic refresh
- TLS/SSL encryption
- Multipart emails (HTML + plaintext)
- Transient error detection for retry logic

Author: Odiseo
Version: 2.1.0
"""

from __future__ import annotations

import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from email_service.config import EmailConfig
from email_service.core.exceptions import SMTPClientError
from email_service.core.logger import get_logger
from email_service.models.smtp_config import SMTPConfig

logger = get_logger(__name__)


class SMTPClient:
    """SMTP email delivery client with connection reuse.

    Sends emails via SMTP with support for multiple providers
    (Gmail, SendGrid, AWS SES). Reuses connections for better
    performance with automatic refresh on staleness.

    Attributes:
        config: SMTP configuration.
        connection_timeout: Seconds before connection is considered stale.
    """

    # Connection timeout in seconds (refresh after this time)
    CONNECTION_TIMEOUT = 60

    def __init__(self, smtp_config: SMTPConfig | None = None) -> None:
        """Initialize SMTP client.

        Args:
            smtp_config: SMTP configuration (uses EmailConfig if None).
        """
        if smtp_config:
            self.config = smtp_config
        else:
            email_config = EmailConfig()
            config_dict = email_config.get_smtp_config()
            self.config = SMTPConfig(
                host=str(config_dict["host"]),
                port=int(config_dict["port"]),
                username=str(config_dict["username"]),
                password=str(config_dict["password"]),
                from_email=str(config_dict["from_email"]),
                from_name=str(config_dict["from_name"]),
                use_tls=bool(config_dict["use_tls"]),
                timeout=int(config_dict["timeout"]),
            )

        # Connection state
        self._connection: smtplib.SMTP | None = None
        self._last_used: float = 0
        self._lock = threading.Lock()

        logger.info(f"SMTP Client initialized: {self.config.host}:{self.config.port}")

    def _get_connection(self) -> smtplib.SMTP:
        """Get or create SMTP connection with automatic refresh.

        Returns:
            Active SMTP connection.

        Raises:
            SMTPClientError: If connection cannot be established.
        """
        with self._lock:
            now = time.time()

            # Check if existing connection is valid
            if self._connection and (now - self._last_used) < self.CONNECTION_TIMEOUT:
                try:
                    # Verify connection is still alive
                    status = self._connection.noop()[0]
                    if status == 250:
                        self._last_used = now
                        return self._connection
                except (smtplib.SMTPException, OSError):
                    logger.debug("Stale SMTP connection detected, reconnecting...")
                    self._close_connection()

            # Create new connection
            return self._create_connection()

    def _create_connection(self) -> smtplib.SMTP:
        """Create new SMTP connection.

        Returns:
            New SMTP connection.

        Raises:
            SMTPClientError: If connection fails.
        """
        try:
            logger.debug(f"Connecting to SMTP: {self.config.host}:{self.config.port}")
            smtp = smtplib.SMTP(
                self.config.host,
                self.config.port,
                timeout=self.config.timeout,
            )

            if self.config.use_tls:
                logger.debug("Starting TLS...")
                smtp.starttls()

            logger.debug("Authenticating...")
            smtp.login(self.config.username, self.config.password)

            self._connection = smtp
            self._last_used = time.time()

            logger.debug("SMTP connection established")
            return smtp

        except Exception as e:
            logger.error(f"Failed to establish SMTP connection: {e}")
            raise SMTPClientError(
                f"Failed to connect to SMTP server: {e}",
                is_transient=self._is_transient_error(e),
            ) from e

    def _close_connection(self) -> None:
        """Close existing SMTP connection safely."""
        if self._connection:
            try:
                self._connection.quit()
            except Exception as e:
                # P005 fix: Log connection close errors for debugging
                logger.debug(f"Error closing SMTP connection (non-critical): {e}")
            finally:
                self._connection = None
                self._last_used = 0

    def send_email(
        self,
        recipient_email: str,
        recipient_name: str | None,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> None:
        """Send an email via SMTP.

        Args:
            recipient_email: Recipient email address.
            recipient_name: Recipient full name (optional).
            subject: Email subject line.
            body_html: HTML-formatted email body.
            body_text: Plain-text fallback (optional).

        Raises:
            SMTPClientError: If email sending fails.
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{self.config.from_name} <{self.config.from_email}>"
            msg["To"] = (
                f"{recipient_name} <{recipient_email}>"
                if recipient_name
                else recipient_email
            )
            msg["Subject"] = subject

            if body_text:
                part_text = MIMEText(body_text, "plain", "utf-8")
                msg.attach(part_text)

            part_html = MIMEText(body_html, "html", "utf-8")
            msg.attach(part_html)

            self._send_message(msg, recipient_email)

            logger.info(f"Email sent to {recipient_email} - Subject: {subject[:50]}...")

        except SMTPClientError:
            raise
        except Exception as e:
            logger.error(f"Failed to send email to {recipient_email}: {e}", exc_info=True)
            raise SMTPClientError(
                f"Failed to send email to {recipient_email}: {str(e)}",
                is_transient=self._is_transient_error(e),
            ) from e

    def _send_message(self, msg: MIMEMultipart, recipient_email: str) -> None:
        """Send message via SMTP connection with retry on stale connection.

        Args:
            msg: Email message to send.
            recipient_email: Recipient email address.
        """
        max_retries = 2

        for attempt in range(max_retries):
            try:
                smtp = self._get_connection()
                smtp.send_message(
                    msg,
                    from_addr=self.config.from_email,
                    to_addrs=[recipient_email],
                )
                return

            except (smtplib.SMTPException, OSError) as e:
                logger.warning(
                    f"SMTP send failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                # Close stale connection and retry
                with self._lock:
                    self._close_connection()

                if attempt == max_retries - 1:
                    raise SMTPClientError(
                        f"Failed to send email after {max_retries} attempts: {e}",
                        is_transient=True,
                    ) from e

    def validate_connection(self) -> bool:
        """Test SMTP connection and authentication.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            logger.info("Testing SMTP connection...")
            self._get_connection()
            logger.info("SMTP connection test successful")
            return True

        except Exception as e:
            logger.error(f"SMTP connection test failed: {e}")
            return False

    def send_test_email(self, test_recipient: str) -> bool:
        """Send a test email to verify configuration.

        Args:
            test_recipient: Email address to send test email to.

        Returns:
            True if test email sent successfully, False otherwise.
        """
        try:
            logger.info(f"Sending test email to {test_recipient}...")
            self.send_email(
                recipient_email=test_recipient,
                recipient_name="Test User",
                subject="Email Service - Test Email",
                body_html="<h1>Test Email</h1><p>Email service is working correctly.</p>",
                body_text="Test Email\n\nEmail service is working correctly.",
            )
            logger.info("Test email sent successfully")
            return True

        except Exception as e:
            logger.error(f"Test email failed: {e}")
            return False

    def close(self) -> None:
        """Close SMTP connection and cleanup resources."""
        with self._lock:
            self._close_connection()
            logger.debug("SMTP client closed")

    @staticmethod
    def _is_transient_error(error: Exception) -> bool:
        """Determine if error is temporary (retryable).

        Args:
            error: Exception to analyze.

        Returns:
            True if error is likely transient and retry may succeed.
        """
        error_str = str(error).lower()
        transient_keywords = [
            "timeout",
            "connection",
            "temporarily",
            "try again",
            "unavailable",
            "service",
            "refused",
            "reset",
            "broken pipe",
        ]
        return any(keyword in error_str for keyword in transient_keywords)

    def __enter__(self) -> SMTPClient:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close connection."""
        self.close()
