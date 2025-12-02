"""Database module for email service.

Contains database operations and PostgreSQL integration.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from email_service.database.queue import EmailQueueManager

__all__ = ["EmailQueueManager"]
