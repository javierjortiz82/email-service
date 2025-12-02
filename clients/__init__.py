"""Clients module for email service.

Contains integrations with external services like SMTP servers.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from email_service.clients.smtp import SMTPClient

__all__ = ["SMTPClient"]
