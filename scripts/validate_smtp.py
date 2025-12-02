#!/usr/bin/env python3
"""Validate SMTP configuration and connectivity.

Tests SMTP server reachability, TLS/SSL, and authentication.

Usage:
    python -m email_service.scripts.validate_smtp
    python -m email_service.scripts.validate_smtp --verbose
    python -m email_service.scripts.validate_smtp --test-email user@example.com
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from email_service.config import EmailConfig
from email_service.core.logger import setup_logging, get_logger
from email_service.clients.smtp import SMTPClient

logger = get_logger(__name__)


def print_header() -> None:
    """Print script header."""
    print("\n" + "=" * 80)
    print("  📧 SMTP Email Service Configuration Validator")
    print("=" * 80)


def print_footer() -> None:
    """Print script footer."""
    print("=" * 80 + "\n")


def print_config(config: EmailConfig) -> None:
    """Print loaded SMTP configuration (with credentials masked).

    Args:
        config: EmailConfig instance.
    """
    smtp_cfg = config.get_smtp_config()

    print("\n📋 Loaded Configuration:")
    print(f"  SMTP Host:      {smtp_cfg['host']}")
    print(f"  SMTP Port:      {smtp_cfg['port']}")
    print(f"  SMTP Username:  {smtp_cfg['username']}")
    print(f"  SMTP From:      {smtp_cfg['from_email']} ({smtp_cfg['from_name']})")
    print(f"  TLS Enabled:    {'Yes' if smtp_cfg['use_tls'] else 'No'}")
    print(f"  Timeout:        {smtp_cfg['timeout']}s")
    print(f"  Database URL:   postgresql://***@{config.DATABASE_URL.split('@')[1] if '@' in config.DATABASE_URL else 'unknown'}")
    print(f"  Schema:         {config.SCHEMA_NAME}")


def validate_smtp_connection() -> bool:
    """Validate SMTP connection.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        print("\n🧪 Testing SMTP Connection...")
        client = SMTPClient()

        if client.validate_connection():
            print("✅ SMTP connection test PASSED")
            return True
        else:
            print("❌ SMTP connection test FAILED")
            return False

    except Exception as e:
        print(f"❌ Error during SMTP validation: {e}")
        logger.exception("SMTP validation error", exc_info=True)
        return False


def send_test_email(test_recipient: str) -> bool:
    """Send test email to verify configuration.

    Args:
        test_recipient: Email address to send test to.

    Returns:
        True if test email sent successfully, False otherwise.
    """
    try:
        print(f"\n📧 Sending Test Email to: {test_recipient}")
        client = SMTPClient()

        if client.send_test_email(test_recipient):
            print(f"✅ Test email sent successfully to {test_recipient}")
            print("   Check your inbox for the test email!")
            return True
        else:
            print(f"❌ Failed to send test email to {test_recipient}")
            return False

    except Exception as e:
        print(f"❌ Error sending test email: {e}")
        logger.exception("Test email error", exc_info=True)
        return False


def print_recommendations(success: bool, test_email_success: Optional[bool] = None) -> None:
    """Print recommendations based on test results.

    Args:
        success: Whether SMTP connection test passed.
        test_email_success: Whether test email was sent (None if not attempted).
    """
    print("\n" + "-" * 80)
    print("📌 Recommendations:")

    if success:
        if test_email_success is None:
            print("  ✅ SMTP configuration is valid and connection works!")
            print("  → You can now start the email service with: python -m email_service.worker")
            print("  → Or optionally test with: --test-email your-email@example.com")
        elif test_email_success:
            print("  ✅ SMTP configuration is valid and test email was delivered!")
            print("  → Email service is ready for production deployment")
            print("  → Start with: python -m email_service.worker")
        else:
            print("  ⚠️  SMTP connection works but test email delivery failed")
            print("  → Check recipient email address format")
            print("  → Verify email isn't blocked by spam filters")
            print("  → Try again with --test-email")
    else:
        print("  ❌ SMTP connection failed. Troubleshooting steps:")
        print("  1. Verify SMTP_HOST and SMTP_PORT in .env file")
        print("     - Gmail: smtp.gmail.com:587 (TLS required)")
        print("     - SendGrid: smtp.sendgrid.net:587")
        print("     - AWS SES: email-smtp.[region].amazonaws.com:587")
        print()
        print("  2. Verify SMTP credentials in .env file")
        print("     - SMTP_USER: your email address")
        print("     - SMTP_PASSWORD: application-specific password (not main password)")
        print("     - Gmail: Use 16-char app password from Account Settings")
        print()
        print("  3. Check firewall/network settings")
        print("     - Verify outbound TCP connection to SMTP port is allowed")
        print("     - Some networks block SMTP ports (25, 587, 465)")
        print()
        print("  4. Verify TLS settings")
        print("     - Most servers use TLS (SMTP_USE_TLS=true)")
        print("     - Some use SSL (port 465 with TLS)")
        print()
        print("  5. Enable debug logging to see detailed errors:")
        print("     - Set LOG_LEVEL=DEBUG in .env file")
        print("     - Run script again with --verbose")
        print()
        print("  6. For Gmail users specifically:")
        print("     - Enable 'Less secure app access' OR use 16-char app password")
        print("     - https://accounts.google.com/u/0/security/apppasswords")


def main() -> int:
    """Main entry point.

    Returns:
        0 if all tests passed, 1 if any test failed.
    """
    parser = argparse.ArgumentParser(
        description="Validate SMTP email service configuration and connectivity.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick validation
  python -m email_service.scripts.validate_smtp

  # Verbose output with debug info
  python -m email_service.scripts.validate_smtp --verbose

  # Test email delivery
  python -m email_service.scripts.validate_smtp --test-email user@example.com

  # Silent mode (only exit code)
  python -m email_service.scripts.validate_smtp --quiet
        """,
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging output",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (only errors and results)",
    )
    parser.add_argument(
        "--test-email",
        "-t",
        type=str,
        metavar="EMAIL",
        help="Send a test email to the specified address",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Suppress header and footer output",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(
        log_level="DEBUG" if args.verbose else "INFO",
        console_level="DEBUG" if args.verbose else "WARNING" if args.quiet else "INFO",
        enable_file=False,
    )

    # Print header
    if not args.no_header:
        print_header()

    exit_code = 0

    try:
        # Load configuration
        config = EmailConfig()

        if not args.quiet:
            print_config(config)

        # Test SMTP connection
        connection_success = validate_smtp_connection()

        # Send test email if requested
        test_email_success = None
        if args.test_email:
            test_email_success = send_test_email(args.test_email)

        # Print recommendations
        if not args.quiet:
            print_recommendations(connection_success, test_email_success)

        # Determine exit code
        if connection_success:
            if args.test_email and not test_email_success:
                exit_code = 1  # Connection OK but email failed
            else:
                exit_code = 0  # Connection OK
        else:
            exit_code = 1  # Connection failed

    except Exception as e:
        if not args.quiet:
            print(f"\n❌ Validation script error: {e}")
        logger.exception("Validation script failed", exc_info=True)
        exit_code = 1

    finally:
        if not args.no_header:
            print_footer()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
