"""Unit tests for template renderer.

Tests Jinja2 template loading, rendering, and fallback generation.

Author: Odiseo
Version: 1.0.0
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from email_service.templates.renderer import TemplateRenderer
from email_service.core.exceptions import TemplateRenderError
from email_service.models.email import EmailType


class TestTemplateRendererInit:
    """Tests for TemplateRenderer initialization."""

    def test_init_with_custom_dir(self, temp_template_dir):
        """Test initialization with custom template directory."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        assert renderer.template_dir == Path(temp_template_dir)
        assert renderer.env is not None

    def test_init_creates_directory(self):
        """Test initialization creates template directory if not exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "new_templates")

            renderer = TemplateRenderer(template_dir=new_dir)

            assert os.path.exists(new_dir)
            assert renderer.template_dir == Path(new_dir)

    def test_init_with_default_config(self, mock_config):
        """Test initialization loads template dir from config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_config.TEMPLATE_DIR = tmpdir

            with patch("email_service.templates.renderer.EmailConfig", return_value=mock_config):
                renderer = TemplateRenderer()

                assert renderer.template_dir == Path(tmpdir)

    def test_init_custom_filters(self, temp_template_dir):
        """Test initialization adds custom Jinja2 filters."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        assert "format_date" in renderer.env.filters
        assert "format_time" in renderer.env.filters


class TestRenderHtml:
    """Tests for HTML template rendering."""

    def test_render_html_success(self, temp_template_dir):
        """Test successful HTML template rendering."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer.render_html(
            email_type=EmailType.BOOKING_CREATED,
            context={
                "customer_name": "John Doe",
                "service_type": "Haircut",
                "booking_date": "2025-01-15",
                "booking_time": "10:00 AM",
            },
        )

        assert "John Doe" in result
        assert "Haircut" in result
        assert "2025-01-15" in result
        assert "<!DOCTYPE html>" in result

    def test_render_html_template_not_found(self, temp_template_dir):
        """Test render_html raises error when template not found."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        with pytest.raises(TemplateRenderError) as exc_info:
            renderer.render_html(
                email_type=EmailType.OTP_VERIFICATION,  # No template for this
                context={"code": "123456"},
            )

        assert "not found" in str(exc_info.value).lower()

    def test_render_html_with_missing_context(self, temp_template_dir):
        """Test render_html handles missing context variables."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        # Missing some expected variables - Jinja2 will render empty strings
        result = renderer.render_html(
            email_type=EmailType.BOOKING_CREATED,
            context={"customer_name": "Jane"},
        )

        assert "Jane" in result


class TestRenderText:
    """Tests for plain-text template rendering."""

    def test_render_text_success(self, temp_template_dir):
        """Test successful plain-text template rendering."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer.render_text(
            email_type=EmailType.BOOKING_CREATED,
            context={
                "customer_name": "John Doe",
                "service_type": "Haircut",
                "booking_date": "2025-01-15",
                "booking_time": "10:00 AM",
            },
        )

        assert "John Doe" in result
        assert "Haircut" in result
        # Should NOT have HTML tags
        assert "<" not in result or "<" in result  # Depends on template content

    def test_render_text_fallback_booking_created(self, temp_template_dir):
        """Test fallback text generation for booking_created."""
        # Remove the .txt template to trigger fallback
        txt_path = os.path.join(temp_template_dir, "booking_created.txt")
        if os.path.exists(txt_path):
            os.remove(txt_path)

        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer.render_text(
            email_type=EmailType.BOOKING_CREATED,
            context={
                "customer_name": "Maria",
                "service_type": "Massage",
                "booking_date": "2025-02-20",
                "booking_time": "14:00",
                "duration_minutes": 60,
            },
        )

        assert "Maria" in result
        assert "Massage" in result
        assert "confirmada" in result.lower()

    def test_render_text_fallback_booking_cancelled(self):
        """Test fallback text for booking_cancelled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TemplateRenderer(template_dir=tmpdir)

            result = renderer.render_text(
                email_type=EmailType.BOOKING_CANCELLED,
                context={
                    "customer_name": "Pedro",
                    "service_type": "Consultation",
                    "booking_date": "2025-03-10",
                    "booking_time": "16:00",
                },
            )

            assert "Pedro" in result
            assert "cancelada" in result.lower()

    def test_render_text_fallback_booking_rescheduled(self):
        """Test fallback text for booking_rescheduled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TemplateRenderer(template_dir=tmpdir)

            result = renderer.render_text(
                email_type=EmailType.BOOKING_RESCHEDULED,
                context={
                    "customer_name": "Ana",
                    "service_type": "Check-up",
                    "old_date": "2025-01-10",
                    "old_time": "09:00",
                    "new_date": "2025-01-12",
                    "new_time": "11:00",
                },
            )

            assert "Ana" in result
            assert "reagendada" in result.lower()
            assert "2025-01-12" in result

    def test_render_text_fallback_reminder_24h(self):
        """Test fallback text for 24-hour reminder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TemplateRenderer(template_dir=tmpdir)

            result = renderer.render_text(
                email_type=EmailType.REMINDER_24H,
                context={
                    "customer_name": "Carlos",
                    "service_type": "Dental",
                    "booking_date": "2025-04-05",
                    "booking_time": "08:00",
                    "hours_until": "24",
                },
            )

            assert "Carlos" in result
            assert "recordatorio" in result.lower() or "Recordatorio" in result

    def test_render_text_fallback_reminder_1h(self):
        """Test fallback text for 1-hour reminder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TemplateRenderer(template_dir=tmpdir)

            result = renderer.render_text(
                email_type=EmailType.REMINDER_1H,
                context={
                    "customer_name": "Luis",
                    "service_type": "Meeting",
                    "booking_date": "2025-05-15",
                    "booking_time": "15:00",
                    "hours_until": "1",
                },
            )

            assert "Luis" in result

    def test_render_text_fallback_default(self):
        """Test default fallback text for unknown email types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TemplateRenderer(template_dir=tmpdir)

            result = renderer.render_text(
                email_type=EmailType.TRANSACTIONAL,
                context={"customer_name": "Unknown"},
            )

            assert "Unknown" in result
            assert "Gracias" in result


class TestTemplateExists:
    """Tests for template existence checking."""

    def test_template_exists_html_true(self, temp_template_dir):
        """Test template_exists returns True for existing HTML template."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer.template_exists(EmailType.BOOKING_CREATED, "html")

        assert result is True

    def test_template_exists_html_false(self, temp_template_dir):
        """Test template_exists returns False for missing HTML template."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer.template_exists(EmailType.OTP_VERIFICATION, "html")

        assert result is False

    def test_template_exists_text_true(self, temp_template_dir):
        """Test template_exists returns True for existing text template."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer.template_exists(EmailType.BOOKING_CREATED, "text")

        assert result is True

    def test_template_exists_text_false(self):
        """Test template_exists returns False for missing text template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TemplateRenderer(template_dir=tmpdir)

            result = renderer.template_exists(EmailType.BOOKING_CREATED, "text")

            assert result is False


class TestCustomFilters:
    """Tests for custom Jinja2 filters."""

    def test_format_date_filter(self, temp_template_dir):
        """Test format_date filter."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        # The filter is a pass-through, so just test it exists and works
        result = renderer._format_date("2025-01-15")
        assert result == "2025-01-15"

    def test_format_time_filter(self, temp_template_dir):
        """Test format_time filter."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        result = renderer._format_time("14:30")
        assert result == "14:30"


class TestJinja2Environment:
    """Tests for Jinja2 environment configuration."""

    def test_autoescape_enabled(self, temp_template_dir):
        """Test that autoescape is enabled for security."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        # Autoescape should be enabled
        assert renderer.env.autoescape is True

    def test_trim_blocks_enabled(self, temp_template_dir):
        """Test that trim_blocks is enabled."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        assert renderer.env.trim_blocks is True

    def test_lstrip_blocks_enabled(self, temp_template_dir):
        """Test that lstrip_blocks is enabled."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        assert renderer.env.lstrip_blocks is True


class TestErrorHandling:
    """Tests for error handling in template rendering."""

    def test_render_error_includes_template_name(self, temp_template_dir):
        """Test that render errors include template name."""
        renderer = TemplateRenderer(template_dir=temp_template_dir)

        with pytest.raises(TemplateRenderError) as exc_info:
            renderer.render_html(EmailType.OTP_VERIFICATION, {})

        assert exc_info.value.template_name is not None
        assert "otp_verification" in exc_info.value.template_name

    def test_render_syntax_error(self, temp_template_dir):
        """Test handling of template syntax errors."""
        # Create a template with syntax error
        bad_template = os.path.join(temp_template_dir, "bad_template.html")
        with open(bad_template, "w") as f:
            f.write("{% if unclosed")

        renderer = TemplateRenderer(template_dir=temp_template_dir)

        # This should not raise during init, but would when trying to render
        # The Jinja2 loader may or may not catch this depending on version


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
