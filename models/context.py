"""Email template context models.

Defines Pydantic models for different email template contexts,
ensuring type-safe context dictionaries for Jinja2 rendering.

Author: Odiseo
Created: 2025-10-18
Version: 1.0.0
"""

from pydantic import BaseModel, Field


class EmailTemplateContext(BaseModel):
    """Base context model for email templates.

    Provides common fields shared by all email template types.
    Subclass this for specific email types requiring additional fields.

    Attributes:
        customer_name: Full name of the customer.
        booking_id: Related booking ID (optional).
    """

    customer_name: str = Field(..., description="Customer name")
    booking_id: int | None = Field(default=None, description="Related booking ID")


class BookingCreatedContext(EmailTemplateContext):
    """Context for booking creation confirmation email.

    Contains all information needed to render a booking confirmation
    email template with appointment details.

    Attributes:
        service_type: Type of service being booked.
        booking_date: Appointment date (e.g., "2025-10-20").
        booking_time: Appointment time (e.g., "14:30").
        duration_minutes: Duration of appointment in minutes.
        google_calendar_link: Optional Google Calendar event link.
    """

    service_type: str = Field(..., description="Service type")
    booking_date: str = Field(..., description="Appointment date")
    booking_time: str = Field(..., description="Appointment time")
    duration_minutes: int = Field(..., ge=1, description="Duration in minutes")
    google_calendar_link: str | None = Field(
        default=None, description="Google Calendar link"
    )


class BookingCancelledContext(EmailTemplateContext):
    """Context for booking cancellation notification email.

    Contains appointment details for the cancellation notice.

    Attributes:
        service_type: Type of service that was booked.
        booking_date: Original appointment date.
        booking_time: Original appointment time.
        cancellation_reason: Reason for cancellation (optional).
    """

    service_type: str = Field(..., description="Service type")
    booking_date: str = Field(..., description="Appointment date")
    booking_time: str = Field(..., description="Appointment time")
    cancellation_reason: str | None = Field(
        default=None, description="Reason for cancellation"
    )


class BookingRescheduledContext(EmailTemplateContext):
    """Context for booking reschedule notification email.

    Contains original and new appointment details.

    Attributes:
        service_type: Type of service being rescheduled.
        old_date: Original appointment date.
        old_time: Original appointment time.
        new_date: New appointment date.
        new_time: New appointment time.
        google_calendar_link: Optional Google Calendar event link.
    """

    service_type: str = Field(..., description="Service type")
    old_date: str = Field(..., description="Original date")
    old_time: str = Field(..., description="Original time")
    new_date: str = Field(..., description="New appointment date")
    new_time: str = Field(..., description="New appointment time")
    google_calendar_link: str | None = Field(
        default=None, description="Google Calendar link"
    )


class ReminderContext(EmailTemplateContext):
    """Context for appointment reminder email templates.

    Shared context for both 24-hour and 1-hour reminders, optionally
    including hours-until-appointment information.

    Attributes:
        service_type: Type of service.
        booking_date: Appointment date.
        booking_time: Appointment time.
        duration_minutes: Duration of appointment in minutes.
        hours_until: Hours remaining until appointment (optional).
        google_calendar_link: Optional Google Calendar event link.
    """

    service_type: str = Field(..., description="Service type")
    booking_date: str = Field(..., description="Appointment date")
    booking_time: str = Field(..., description="Appointment time")
    duration_minutes: int = Field(..., ge=1, description="Duration in minutes")
    hours_until: int | None = Field(
        default=None, ge=0, description="Hours until appointment"
    )
    google_calendar_link: str | None = Field(
        default=None, description="Google Calendar link"
    )
