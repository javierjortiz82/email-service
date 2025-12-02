"""Configuration module for email service.

Loads and validates email service settings from environment variables or .env file.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from email_service.config.settings import EmailConfig

__all__ = ["EmailConfig"]

# Global settings instance
settings = EmailConfig()
