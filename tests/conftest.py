"""Pytest configuration and fixtures for email service tests.

Provides reusable fixtures for unit and integration tests including
mocked database connections, SMTP clients, and FastAPI test client.

Author: Odiseo
Version: 1.0.0
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

# Set test environment before importing application modules
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/testdb")
os.environ.setdefault("SMTP_HOST", "smtp.test.com")
os.environ.setdefault("SMTP_USER", "test@test.com")
os.environ.setdefault("SMTP_PASSWORD", "testpassword")
os.environ.setdefault("SMTP_FROM_EMAIL", "noreply@test.com")
os.environ.setdefault("LOG_TO_FILE", "false")


# =============================================================================
# Email Configuration Fixtures
# =============================================================================
@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock EmailConfig for testing."""
    config = MagicMock()
    config.DATABASE_URL = "postgresql://test:test@localhost:5432/testdb"
    config.SCHEMA_NAME = "test"
    config.SMTP_HOST = "smtp.test.com"
    config.SMTP_PORT = 587
    config.SMTP_USER = "test@test.com"
    config.SMTP_PASSWORD = "testpassword"
    config.SMTP_FROM_EMAIL = "noreply@test.com"
    config.SMTP_FROM_NAME = "Test Service"
    config.SMTP_USE_TLS = True
    config.SMTP_TIMEOUT = 30
    config.SERVICE_NAME = "email-service-test"
    config.SERVICE_VERSION = "2.0.0"
    config.API_HOST = "0.0.0.0"
    config.API_PORT = 8001
    config.API_KEY = ""
    config.RATE_LIMIT_PER_MINUTE = 60
    config.RATE_LIMIT_PER_SECOND = 10
    config.LOG_LEVEL = "DEBUG"
    config.LOG_TO_FILE = False
    config.TEMPLATE_DIR = "/tmp/templates"
    config.EMAIL_WORKER_POLL_INTERVAL = 10
    config.EMAIL_WORKER_BATCH_SIZE = 50
    config.EMAIL_RETRY_MAX_ATTEMPTS = 3
    config.EMAIL_RETRY_BACKOFF_SECONDS = 300
    config.validate_smtp_config = MagicMock()
    config.get_smtp_config = MagicMock(return_value={
        "host": "smtp.test.com",
        "port": 587,
        "username": "test@test.com",
        "password": "testpassword",
        "from_email": "noreply@test.com",
        "from_name": "Test Service",
        "use_tls": True,
        "timeout": 30,
    })
    return config


# =============================================================================
# SMTP Client Fixtures
# =============================================================================
@pytest.fixture
def mock_smtp_config() -> MagicMock:
    """Create a mock SMTPConfig for testing."""
    from email_service.models.smtp_config import SMTPConfig
    return SMTPConfig(
        host="smtp.test.com",
        port=587,
        username="test@test.com",
        password="testpassword",
        from_email="noreply@test.com",
        from_name="Test Service",
        use_tls=True,
        timeout=30,
    )


@pytest.fixture
def mock_smtp_connection() -> MagicMock:
    """Create a mock SMTP connection."""
    smtp = MagicMock()
    smtp.noop.return_value = (250, b"OK")
    smtp.send_message.return_value = {}
    smtp.starttls.return_value = (220, b"TLS ready")
    smtp.login.return_value = (235, b"Authentication successful")
    smtp.quit.return_value = (221, b"Bye")
    return smtp


# =============================================================================
# Database Fixtures
# =============================================================================
@pytest.fixture
def mock_db_connection() -> MagicMock:
    """Create a mock database connection."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value = cursor
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    return conn


@pytest.fixture
def mock_connection_pool(mock_db_connection: MagicMock) -> MagicMock:
    """Create a mock connection pool."""
    pool = MagicMock()
    pool.getconn.return_value = mock_db_connection
    pool.putconn = MagicMock()
    pool.closeall = MagicMock()
    return pool


# =============================================================================
# Email Record Fixtures
# =============================================================================
@pytest.fixture
def sample_email_record() -> dict[str, Any]:
    """Create a sample email record dictionary.

    Note: This mimics the raw database row format returned by psycopg2.
    The EmailRecord model expects `created_at` and `updated_at` to come
    from the dictionary, not as separate arguments.
    """
    now = datetime.now()
    return {
        "id": 1,
        "type": "transactional",
        "recipient_email": "user@example.com",
        "recipient_name": "Test User",
        "subject": "Test Email Subject",
        "body_html": "<h1>Hello</h1><p>Test email body</p>",
        "body_text": "Hello\n\nTest email body",
        "status": "pending",
        "retry_count": 0,
        "max_retries": 3,
        "last_error": None,
        "next_retry_at": None,
        "scheduled_for": now,
        "sent_at": None,
        "priority": 5,
        "booking_id": None,
        "template_context": {"customer_name": "Test User"},
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture
def sample_email_request() -> dict[str, Any]:
    """Create a sample email API request."""
    return {
        "to": ["user@example.com"],
        "subject": "Test Email",
        "body": "<h1>Hello</h1><p>Test body</p>",
        "template_id": None,
        "template_vars": {},
    }


# =============================================================================
# Template Fixtures
# =============================================================================
@pytest.fixture
def temp_template_dir() -> Generator[str, None, None]:
    """Create a temporary directory with test templates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create sample HTML template
        html_template = tmpdir + "/booking_created.html"
        with open(html_template, "w") as f:
            f.write("""<!DOCTYPE html>
<html>
<head><title>Booking Confirmed</title></head>
<body>
<h1>Hello {{ customer_name }}!</h1>
<p>Your booking has been confirmed:</p>
<ul>
    <li>Service: {{ service_type }}</li>
    <li>Date: {{ booking_date }}</li>
    <li>Time: {{ booking_time }}</li>
</ul>
</body>
</html>""")

        # Create sample text template
        txt_template = tmpdir + "/booking_created.txt"
        with open(txt_template, "w") as f:
            f.write("""Hello {{ customer_name }}!

Your booking has been confirmed:

Service: {{ service_type }}
Date: {{ booking_date }}
Time: {{ booking_time }}""")

        yield tmpdir


# =============================================================================
# FastAPI Test Client Fixtures
# =============================================================================
@pytest.fixture
def mock_queue_manager() -> MagicMock:
    """Create a mock EmailQueueManager."""
    manager = MagicMock()
    manager.enqueue_email.return_value = 1
    manager.get_queue_stats.return_value = {
        "pending": 5,
        "scheduled": 2,
        "processing": 1,
        "sent": 100,
        "failed": 3,
    }
    manager.health_check.return_value = True
    manager.close = MagicMock()
    return manager


@pytest.fixture
def test_client(mock_config: MagicMock, mock_queue_manager: MagicMock):
    """Create a FastAPI test client with mocked dependencies."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import email_service.api.main as main_module
    from email_service.api.main import AppState

    # Reset rate limiter before each test
    main_module.rate_limiter._requests.clear()

    # Create mock lifespan that doesn't connect to database
    @asynccontextmanager
    async def mock_lifespan(app: FastAPI):
        main_module.app_state = AppState(
            config=mock_config,
            queue_manager=mock_queue_manager,
        )
        yield
        main_module.app_state = None

    # Create a test app with mocked lifespan
    test_app = FastAPI(
        title="email-service-test",
        lifespan=mock_lifespan,
    )

    # Copy routes from the real app
    for route in main_module.app.routes:
        test_app.routes.append(route)

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield client

    # Cleanup rate limiter after test
    main_module.rate_limiter._requests.clear()


@pytest.fixture
def authenticated_client(test_client, mock_config: MagicMock):
    """Create a test client with API key authentication."""
    # Enable API key authentication
    mock_config.API_KEY = "test-api-key-12345"

    class AuthenticatedClient:
        def __init__(self, client):
            self.client = client
            self.headers = {"X-API-Key": "test-api-key-12345"}

        def get(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self.headers)
            return self.client.get(url, **kwargs)

        def post(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self.headers)
            return self.client.post(url, **kwargs)

    return AuthenticatedClient(test_client)
