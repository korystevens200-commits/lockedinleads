"""
Owner notifications.

Three channels — dashboard (always), email and SMS (when enabled per tenant and
configured on the server). Which events fire is a per-tenant setting.
"""

from .. import config, repo
from ..automation import schedule
from .mailer import send_email
from .sms import send_sms


def _recipients(tenant):
    notif = tenant["settings"]["notifications"]
    email_to = (notif.get("email_to") or tenant.get("contact_email") or "").strip()
    sms_to = (notif.get("sms_to") or tenant.get("contact_phone") or "").strip()
    return notif, email_to, sms_to


def _dispatch(tenant, event, title, body, lead_id=None, sms_body=None):
    notif, email_to, sms_to = _recipients(tenant)
    if not notif["events"].get(event, True):
        return
    repo.add_notification(tenant["id"], event, title, body, lead_id)
    if notif.get("email_enabled") and email_to:
        send_email(email_to, f"[{tenant['name']}] {title}", body,
                   tenant_id=tenant["id"], lead_id=lead_id)
    if notif.get("sms_enabled") and sms_to:
        send_sms(sms_to, sms_body or f"{title} — {body[:120]}",
                 tenant_id=tenant["id"], lead_id=lead_id)


def _lead_summary(tenant, lead):
    lines = [
        f"Name: {lead.get('name') or 'Not given yet'}",
        f"Phone: {lead.get('phone') or '—'}",
        f"Email: {lead.get('email') or '—'}",
        f"Source: {lead.get('source_label') or lead.get('source')}",
        f"Service: {lead.get('service_requested') or '—'}",
        f"Location: {lead.get('location') or '—'}",
    ]
    for key, value in (lead.get("qualification") or {}).items():
        lines.append(f"{key.replace('_', ' ').title()}: {value}")
    lines.append(f"\nOpen in dashboard: {config.PUBLIC_URL}/app/leads.html?lead={lead['id']}")
    return "\n".join(lines)


def notify_new_lead(tenant, lead):
    _dispatch(tenant, "new_lead",
              f"New lead: {lead.get('name') or lead.get('phone') or 'Unknown'}",
              _lead_summary(tenant, lead), lead["id"],
              sms_body=f"New lead for {tenant['name']}: {lead.get('name') or lead.get('phone') or 'unknown'}")


def notify_qualified(tenant, lead):
    _dispatch(tenant, "qualified",
              f"Lead qualified: {lead.get('name') or lead.get('phone') or 'Unknown'}",
              _lead_summary(tenant, lead), lead["id"],
              sms_body=f"Qualified lead for {tenant['name']}: {lead.get('name') or 'unknown'}")


def notify_appointment_booked(tenant, lead, appointment):
    when = schedule.format_slot(appointment["starts_at"], tenant, include_year=True)
    body = f"Appointment: {when}\n\n" + _lead_summary(tenant, lead)
    _dispatch(tenant, "booked", f"Appointment booked: {lead.get('name') or 'New customer'} — {when}",
              body, lead["id"],
              sms_body=f"BOOKED: {lead.get('name') or 'lead'} — {when} ({tenant['name']})")


def notify_handoff(tenant, lead, reason=""):
    body = (f"The assistant handed this conversation to you{': ' + reason if reason else '.'}\n\n"
            + _lead_summary(tenant, lead))
    _dispatch(tenant, "handoff", f"Takeover needed: {lead.get('name') or 'Lead'}", body, lead["id"],
              sms_body=f"Takeover needed for {lead.get('name') or 'a lead'} ({tenant['name']})")


def deliver_to_lead(tenant, lead, body):
    """Send an assistant message out over the best available channel.

    Chat-widget leads read replies in the widget itself; SMS/email are used when
    the lead came from a form or ad and the server has those channels wired up.
    Returns the channel the message went out on.
    """
    if lead.get("opted_out"):
        return "suppressed"
    if lead.get("source") == "chat_widget":
        return "chat"
    if lead.get("phone") and config.sms_configured():
        send_sms(lead["phone"], body, tenant_id=tenant["id"], lead_id=lead["id"])
        return "sms"
    if lead.get("email"):
        send_email(lead["email"], f"{tenant['name']}", body,
                   tenant_id=tenant["id"], lead_id=lead["id"], from_name=tenant["name"])
        return "email"
    if lead.get("phone"):
        send_sms(lead["phone"], body, tenant_id=tenant["id"], lead_id=lead["id"])
        return "sms"
    return "chat"
