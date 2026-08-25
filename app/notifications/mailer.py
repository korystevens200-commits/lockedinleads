"""
SMTP email. With no SMTP credentials configured every send is recorded as
'simulated' and logged, so the flow is demonstrable and nothing silently
disappears.
"""

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from .. import config, repo


def send_email(to_address, subject, body, tenant_id=None, lead_id=None, from_name=None):
    to_address = (to_address or "").strip()
    if not to_address:
        return "skipped"

    if not config.email_configured():
        repo.log_outbound(tenant_id, "email", to_address, subject, body, "simulated",
                          "SMTP not configured — logged instead of sent.", lead_id)
        if config.ENV != "test":
            print(f"[email:simulated] to={to_address} subject={subject!r}")
        return "simulated"

    try:
        msg = EmailMessage()
        msg["Subject"] = subject[:200]
        msg["From"] = formataddr((from_name or config.AGENCY_NAME, config.SMTP_FROM))
        msg["To"] = to_address
        msg.set_content(body)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            if config.SMTP_STARTTLS:
                server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        repo.log_outbound(tenant_id, "email", to_address, subject, body, "sent", "", lead_id)
        return "sent"
    except Exception as exc:
        repo.log_outbound(tenant_id, "email", to_address, subject, body, "failed", str(exc), lead_id)
        print(f"[email:failed] to={to_address}: {exc}")
        return "failed"
