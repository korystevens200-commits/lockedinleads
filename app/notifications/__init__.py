"""Notification channels: email, SMS and in-dashboard alerts."""
from .notify import (deliver_to_lead, notify_appointment_booked, notify_handoff,
                     notify_new_lead, notify_qualified)  # noqa: F401
