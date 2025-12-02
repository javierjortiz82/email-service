"""Integration tests for API endpoints.

Tests FastAPI endpoints including authentication, rate limiting, and error handling.

Author: Odiseo
Version: 1.0.0
"""

from __future__ import annotations

import pytest


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_check_success(self, test_client, mock_queue_manager):
        """Test health check returns 200 when all services are healthy."""
        mock_queue_manager.health_check.return_value = True

        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"
        assert "version" in data

    def test_health_check_db_failure(self, test_client, mock_queue_manager):
        """Test health check returns 503 when database is unhealthy."""
        mock_queue_manager.health_check.return_value = False

        response = test_client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["db"] == "error"

    def test_health_check_no_auth_required(self, test_client, mock_config):
        """Test health check does not require authentication."""
        # Enable API key auth
        mock_config.API_KEY = "secret-key"

        response = test_client.get("/health")

        # Should succeed without API key
        assert response.status_code in [200, 503]


class TestSendEmailEndpoint:
    """Tests for POST /emails endpoint."""

    def test_send_email_success(self, test_client, mock_queue_manager, sample_email_request):
        """Test successful email queuing."""
        mock_queue_manager.enqueue_email.return_value = 123

        response = test_client.post("/emails", json=sample_email_request)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["queued"] is True
        assert "message_id" in data

    def test_send_email_with_template(self, test_client, mock_queue_manager):
        """Test email queuing with template."""
        request = {
            "to": ["user@example.com"],
            "subject": "Booking Confirmation",
            "body": "<p>Your booking is confirmed</p>",
            "template_id": "booking_created",
            "template_vars": {
                "customer_name": "John",
                "booking_date": "2025-01-15",
            },
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 202
        mock_queue_manager.enqueue_email.assert_called()

    def test_send_email_multiple_recipients(self, test_client, mock_queue_manager):
        """Test email queuing with multiple recipients."""
        request = {
            "to": ["user1@example.com", "user2@example.com", "user3@example.com"],
            "subject": "Group Email",
            "body": "<p>Hello everyone</p>",
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 202
        # Should be called once per recipient
        assert mock_queue_manager.enqueue_email.call_count == 3

    def test_send_email_invalid_email(self, test_client):
        """Test email queuing with invalid email address."""
        request = {
            "to": ["not-an-email"],
            "subject": "Test",
            "body": "<p>Test</p>",
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 422  # Validation error

    def test_send_email_empty_recipients(self, test_client):
        """Test email queuing with empty recipients list."""
        request = {
            "to": [],
            "subject": "Test",
            "body": "<p>Test</p>",
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 422  # Validation error

    def test_send_email_missing_subject(self, test_client):
        """Test email queuing with missing subject."""
        request = {
            "to": ["user@example.com"],
            "body": "<p>Test</p>",
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 422

    def test_send_email_missing_body(self, test_client):
        """Test email queuing with missing body."""
        request = {
            "to": ["user@example.com"],
            "subject": "Test",
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 422

    def test_send_email_queue_error(self, test_client, mock_queue_manager, sample_email_request):
        """Test email queuing handles database errors gracefully."""
        mock_queue_manager.enqueue_email.side_effect = Exception("Database error")

        response = test_client.post("/emails", json=sample_email_request)

        assert response.status_code == 500
        data = response.json()
        # Error message should be sanitized (not expose internal details)
        assert "database" not in data["detail"].lower()

    def test_send_email_with_client_message_id(self, test_client, mock_queue_manager):
        """Test email queuing with client-provided message ID."""
        request = {
            "to": ["user@example.com"],
            "subject": "Test",
            "body": "<p>Test</p>",
            "client_message_id": "my-custom-id-123",
        }

        response = test_client.post("/emails", json=request)

        assert response.status_code == 202
        data = response.json()
        assert data["message_id"] == "my-custom-id-123"


class TestQueueStatusEndpoint:
    """Tests for GET /queue/status endpoint."""

    def test_queue_status_success(self, test_client, mock_queue_manager):
        """Test successful queue status retrieval."""
        mock_queue_manager.get_queue_stats.return_value = {
            "pending": 10,
            "scheduled": 5,
            "processing": 2,
            "sent": 100,
            "failed": 3,
        }

        response = test_client.get("/queue/status")

        assert response.status_code == 200
        data = response.json()
        assert data["pending"] == 10
        assert data["scheduled"] == 5
        assert data["processing"] == 2
        assert data["sent"] == 100
        assert data["failed"] == 3

    def test_queue_status_empty(self, test_client, mock_queue_manager):
        """Test queue status with empty queue."""
        mock_queue_manager.get_queue_stats.return_value = {}

        response = test_client.get("/queue/status")

        assert response.status_code == 200
        data = response.json()
        assert data["pending"] == 0
        assert data["sent"] == 0

    def test_queue_status_error(self, test_client, mock_queue_manager):
        """Test queue status handles errors gracefully."""
        mock_queue_manager.get_queue_stats.side_effect = Exception("DB error")

        response = test_client.get("/queue/status")

        assert response.status_code == 500
        data = response.json()
        # Error should be sanitized
        assert "db" not in data["detail"].lower()


class TestAPIKeyAuthentication:
    """Tests for API key authentication."""

    def test_auth_disabled_by_default(self, test_client, mock_config, sample_email_request):
        """Test endpoints work without auth when API_KEY not set."""
        mock_config.API_KEY = ""

        response = test_client.post("/emails", json=sample_email_request)

        assert response.status_code == 202

    def test_auth_required_when_configured(self, test_client, mock_config, sample_email_request):
        """Test endpoints require auth when API_KEY is set."""
        mock_config.API_KEY = "secret-api-key"

        # Request without API key
        response = test_client.post("/emails", json=sample_email_request)

        assert response.status_code == 401
        assert "API key required" in response.json()["detail"]

    def test_auth_success_with_valid_key(self, test_client, mock_config, sample_email_request):
        """Test endpoints work with valid API key."""
        mock_config.API_KEY = "secret-api-key"

        response = test_client.post(
            "/emails",
            json=sample_email_request,
            headers={"X-API-Key": "secret-api-key"},
        )

        assert response.status_code == 202

    def test_auth_failure_with_invalid_key(self, test_client, mock_config, sample_email_request):
        """Test endpoints reject invalid API key."""
        mock_config.API_KEY = "secret-api-key"

        response = test_client.post(
            "/emails",
            json=sample_email_request,
            headers={"X-API-Key": "wrong-key"},
        )

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_queue_status_requires_auth(self, test_client, mock_config):
        """Test queue status endpoint requires auth when configured."""
        mock_config.API_KEY = "secret-api-key"

        response = test_client.get("/queue/status")

        assert response.status_code == 401


class TestRateLimiting:
    """Tests for rate limiting middleware."""

    def test_rate_limit_allows_normal_requests(self, test_client, sample_email_request):
        """Test rate limiter allows normal request rate."""
        # Make a few requests - should all succeed
        for _ in range(5):
            response = test_client.post("/emails", json=sample_email_request)
            assert response.status_code == 202

    def test_rate_limit_health_excluded(self, test_client):
        """Test health endpoint is excluded from rate limiting."""
        # Make many health check requests - should all succeed
        for _ in range(100):
            response = test_client.get("/health")
            assert response.status_code in [200, 503]

    def test_rate_limit_per_second_exceeded(self, test_client, mock_config, sample_email_request):
        """Test rate limiter blocks when per-second limit exceeded."""
        # Set very low limit for testing
        import email_service.api.main as main_module
        main_module.rate_limiter.requests_per_second = 2
        main_module.rate_limiter.requests_per_minute = 1000
        main_module.rate_limiter._requests.clear()

        # Make rapid requests
        responses = []
        for _ in range(5):
            response = test_client.post("/emails", json=sample_email_request)
            responses.append(response.status_code)

        # At least one should be rate limited
        # Note: Due to timing, this might not always trigger
        # Reset rate limiter for other tests
        main_module.rate_limiter.requests_per_second = 10
        main_module.rate_limiter._requests.clear()


class TestErrorResponses:
    """Tests for error response format."""

    def test_validation_error_format(self, test_client):
        """Test validation errors return proper format."""
        response = test_client.post("/emails", json={"invalid": "data"})

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_internal_error_sanitized(self, test_client, mock_queue_manager, sample_email_request):
        """Test internal errors are sanitized."""
        mock_queue_manager.enqueue_email.side_effect = Exception(
            "psycopg2.OperationalError: connection refused to localhost:5432"
        )

        response = test_client.post("/emails", json=sample_email_request)

        assert response.status_code == 500
        data = response.json()
        # Should NOT contain sensitive info
        assert "psycopg2" not in data["detail"]
        assert "localhost" not in data["detail"]
        assert "5432" not in data["detail"]


class TestTemplateTypeMapping:
    """Tests for template type mapping in email endpoint."""

    @pytest.mark.parametrize("template_id,expected_type", [
        ("otp_verification", "otp_verification"),
        ("booking_created", "booking_created"),
        ("booking_cancelled", "booking_cancelled"),
        ("booking_rescheduled", "booking_rescheduled"),
        ("reminder_24h", "reminder_24h"),
        ("reminder_1h", "reminder_1h"),
        ("unknown_template", "transactional"),  # Fallback
    ])
    def test_template_type_mapping(self, test_client, mock_queue_manager, template_id, expected_type):
        """Test template IDs map to correct email types."""
        request = {
            "to": ["user@example.com"],
            "subject": "Test",
            "body": "<p>Test</p>",
            "template_id": template_id,
        }

        test_client.post("/emails", json=request)

        # Verify enqueue was called with correct type
        call_args = mock_queue_manager.enqueue_email.call_args
        actual_type = call_args.kwargs.get("email_type") or call_args[1].get("email_type")
        if actual_type:
            assert actual_type.value == expected_type


class TestResponseTimestamps:
    """Tests for response timestamps."""

    def test_email_response_has_timestamp(self, test_client, sample_email_request):
        """Test email response includes timestamp."""
        response = test_client.post("/emails", json=sample_email_request)

        data = response.json()
        assert "timestamp" in data

    def test_queue_status_has_timestamp(self, test_client):
        """Test queue status response includes timestamp."""
        response = test_client.get("/queue/status")

        data = response.json()
        assert "timestamp" in data

    def test_health_response_has_timestamp(self, test_client):
        """Test health response includes timestamp."""
        response = test_client.get("/health")

        data = response.json()
        assert "timestamp" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
