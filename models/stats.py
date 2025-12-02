"""Email statistics model.

Defines Pydantic model for email queue statistics and analytics.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from pydantic import BaseModel, Field


class EmailStats(BaseModel):
    """Email queue statistics model.

    Tracks aggregate metrics about email queue state and performance.

    Attributes:
        total_emails: Total emails ever in queue.
        pending_count: Currently pending emails.
        processing_count: Currently being processed.
        sent_count: Successfully sent emails.
        failed_count: Permanently failed emails.
        scheduled_count: Emails scheduled for future delivery.
        success_rate: Percentage of sent emails (calculated).
        average_retry_count: Average retries per email.
    """

    total_emails: int = Field(default=0, ge=0, description="Total emails")
    pending_count: int = Field(default=0, ge=0, description="Currently pending")
    processing_count: int = Field(default=0, ge=0, description="Currently processing")
    sent_count: int = Field(default=0, ge=0, description="Successfully sent")
    failed_count: int = Field(default=0, ge=0, description="Permanently failed")
    scheduled_count: int = Field(default=0, ge=0, description="Scheduled for future")
    success_rate: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Success rate (%)"
    )
    average_retry_count: float = Field(
        default=0.0, ge=0.0, description="Average retries per email"
    )

    def calculate_success_rate(self) -> None:
        """Calculate and update success rate.

        Computes success rate as percentage of sent emails out of
        total processed (sent + failed).
        """
        total_processed = self.sent_count + self.failed_count
        if total_processed > 0:
            self.success_rate = (self.sent_count / total_processed) * 100
        else:
            self.success_rate = 0.0
