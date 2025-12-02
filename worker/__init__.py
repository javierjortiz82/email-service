"""Worker module for email service.

Contains email queue processing daemon and worker logic.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from email_service.worker.processor import EmailWorker

__all__ = ["EmailWorker"]
