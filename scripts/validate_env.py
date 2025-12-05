"""Validate .env file completeness against configuration requirements.

Checks that all required configuration variables are present in the .env file.

Author: Odiseo
Created: 2025-10-18
"""

import os
import sys
from pathlib import Path

# Required configuration variables
REQUIRED_VARS = {
    # Database
    "DATABASE_URL",
    "SCHEMA_NAME",
    # SMTP
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    "SMTP_FROM_NAME",
    "SMTP_USE_TLS",
    "SMTP_TIMEOUT",
    # Worker
    "EMAIL_WORKER_POLL_INTERVAL",
    "EMAIL_WORKER_BATCH_SIZE",
    "EMAIL_RETRY_MAX_ATTEMPTS",
    "EMAIL_RETRY_BACKOFF_SECONDS",
    # Reminders
    "REMINDER_24H_ENABLED",
    "REMINDER_1H_ENABLED",
    "REMINDER_24H_SUBJECT",
    "REMINDER_1H_SUBJECT",
    # Logging
    "LOG_LEVEL",
    "LOG_TO_FILE",
    "LOG_DIR",
    # Templates
    "TEMPLATE_DIR",
}

def validate_env() -> tuple[bool, list[str]]:
    """Validate .env file has all required variables.

    Returns:
        Tuple of (is_valid, missing_vars).
    """
    missing = []

    for var in REQUIRED_VARS:
        if not os.getenv(var):
            missing.append(var)

    return len(missing) == 0, missing


def main() -> int:
    """Main entry point for validation script.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    # Load .env file if it exists
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        # P004 fix: Handle ImportError gracefully
        try:
            import dotenv
            dotenv.load_dotenv(env_file)
        except ImportError:
            print("Warning: python-dotenv not installed. Install with: pip install python-dotenv")
            print("Continuing with existing environment variables...")
        except Exception as e:
            print(f"Warning: Failed to load .env file: {e}")

    is_valid, missing_vars = validate_env()

    if is_valid:
        print("✅ .env file is valid - all required variables present")
        return 0
    else:
        print("❌ .env file is missing required variables:")
        for var in sorted(missing_vars):
            print(f"   - {var}")
        print("\n📝 Please copy .env.example to .env and fill in the values")
        print("   cp email_service/.env.example .env")
        return 1


if __name__ == "__main__":
    sys.exit(main())
