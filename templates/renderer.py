"""Jinja2 template renderer for email service.

Renders HTML and plain-text email templates with dynamic context data.
Supports all email types (booking confirmations, reminders, cancellations, etc).

Version: 2.0.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from email_service.config import EmailConfig
from email_service.core.exceptions import TemplateRenderError
from email_service.core.logger import get_logger
from email_service.models.email import EmailType

logger = get_logger(__name__)


class TemplateRenderer:
    """Jinja2 template renderer for email templates.

    Loads and renders email templates with dynamic context data.
    Supports both HTML and plain-text variants for each email type.
    """

    def __init__(self, template_dir: str | None = None) -> None:
        """Initialize template renderer.

        Args:
            template_dir: Path to templates directory (uses config if None).

        Raises:
            TemplateRenderError: If template directory cannot be created.
        """
        self.template_dir = Path(template_dir or EmailConfig().TEMPLATE_DIR)

        try:
            self.env = self._init_jinja_env()
            logger.info(f"Template renderer initialized: {self.template_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize template renderer: {e}")
            raise TemplateRenderError(f"Failed to initialize Jinja2: {e}") from e

    def _init_jinja_env(self) -> Environment:
        """Initialize Jinja2 environment with custom settings."""
        try:
            self.template_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise TemplateRenderError(
                f"Cannot create template directory {self.template_dir}: {e}"
            ) from e

        env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        env.filters["format_date"] = self._format_date
        env.filters["format_time"] = self._format_time

        return env

    def render_html(self, email_type: EmailType, context: dict[str, Any]) -> str:
        """Render HTML email template.

        Args:
            email_type: Email type determining which template to load.
            context: Dictionary with template variables.

        Returns:
            Rendered HTML string.

        Raises:
            TemplateRenderError: If template not found or rendering fails.
        """
        template_name = f"{email_type.value}.html"

        try:
            logger.debug(f"Rendering HTML template: {template_name}")

            template = self.env.get_template(template_name)
            rendered = template.render(**context)

            logger.debug(f"HTML template rendered: {len(rendered)} bytes")
            return rendered

        except TemplateNotFound:
            logger.error(f"HTML template not found: {template_name}")
            raise TemplateRenderError(
                f"Template not found: {template_name}",
                template_name=template_name,
            ) from None

        except Exception as e:
            logger.error(f"Failed to render HTML template: {e}")
            raise TemplateRenderError(
                f"Failed to render {template_name}: {e}",
                template_name=template_name,
            ) from e

    def render_text(self, email_type: EmailType, context: dict[str, Any]) -> str:
        """Render plain-text email template.

        Attempts to load .txt template. If not found, generates a fallback.

        Args:
            email_type: Email type determining which template to load.
            context: Dictionary with template variables.

        Returns:
            Rendered plain-text string.

        Raises:
            TemplateRenderError: If rendering fails.
        """
        template_name = f"{email_type.value}.txt"

        try:
            logger.debug(f"Rendering text template: {template_name}")

            template = self.env.get_template(template_name)
            rendered = template.render(**context)

            logger.debug(f"Text template rendered: {len(rendered)} bytes")
            return rendered

        except TemplateNotFound:
            logger.debug(f"Text template not found: {template_name}, using fallback")
            return self._generate_fallback_text(email_type, context)

        except Exception as e:
            logger.error(f"Failed to render text template: {e}")
            raise TemplateRenderError(
                f"Failed to render {template_name}: {e}",
                template_name=template_name,
            ) from e

    def _generate_fallback_text(
        self, email_type: EmailType, context: dict[str, Any]
    ) -> str:
        """Generate plain-text fallback when .txt template doesn't exist."""
        customer_name = context.get("customer_name", "Cliente")

        if email_type == EmailType.BOOKING_CREATED:
            return f"""
Hola {customer_name},

Tu cita ha sido confirmada:

Servicio: {context.get('service_type', 'N/A')}
Fecha: {context.get('booking_date', 'N/A')}
Hora: {context.get('booking_time', 'N/A')}
Duracion: {context.get('duration_minutes', 'N/A')} minutos

Gracias por tu confianza.
            """.strip()

        elif email_type == EmailType.BOOKING_CANCELLED:
            return f"""
Hola {customer_name},

Tu cita ha sido cancelada:

Servicio: {context.get('service_type', 'N/A')}
Fecha: {context.get('booking_date', 'N/A')}
Hora: {context.get('booking_time', 'N/A')}

Gracias por tu confianza.
            """.strip()

        elif email_type == EmailType.BOOKING_RESCHEDULED:
            return f"""
Hola {customer_name},

Tu cita ha sido reagendada:

Servicio: {context.get('service_type', 'N/A')}
Fecha anterior: {context.get('old_date', 'N/A')} - {context.get('old_time', 'N/A')}
Nueva fecha: {context.get('new_date', 'N/A')} - {context.get('new_time', 'N/A')}

Gracias por tu confianza.
            """.strip()

        elif email_type in (EmailType.REMINDER_24H, EmailType.REMINDER_1H):
            hours_until = context.get("hours_until", "24")
            return f"""
Hola {customer_name},

Recordatorio: Tienes una cita en {hours_until} horas.

Servicio: {context.get('service_type', 'N/A')}
Fecha: {context.get('booking_date', 'N/A')}
Hora: {context.get('booking_time', 'N/A')}

Te esperamos!
            """.strip()

        else:
            return f"""
Hola {customer_name},

Gracias por tu confianza.
            """.strip()

    def _format_date(self, date_str: str) -> str:
        """Jinja2 filter to format dates (pass-through)."""
        return date_str

    def _format_time(self, time_str: str) -> str:
        """Jinja2 filter to format times (pass-through)."""
        return time_str

    def template_exists(self, email_type: EmailType, format_type: str = "html") -> bool:
        """Check if template file exists for email type.

        Args:
            email_type: Email type to check.
            format_type: "html" or "text".

        Returns:
            True if template file exists, False otherwise.
        """
        ext = "html" if format_type == "html" else "txt"
        template_path = self.template_dir / f"{email_type.value}.{ext}"
        exists = template_path.exists()
        logger.debug(f"Template check: {template_path} ({'exists' if exists else 'not found'})")
        return exists
