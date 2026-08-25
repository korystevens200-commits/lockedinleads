"""
SMS via Twilio's REST API over urllib — no SDK needed for one endpoint.
Without credentials, sends are simulated and logged like email.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from .. import config, repo, security

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def send_sms(to_number, body, tenant_id=None, lead_id=None):
    to_number = security.normalize_phone(to_number or "")
    if not to_number:
        return "skipped"

    if not config.sms_configured():
        repo.log_outbound(tenant_id, "sms", to_number, "", body, "simulated",
                          "Twilio not configured — logged instead of sent.", lead_id)
        if config.ENV != "test":
            print(f"[sms:simulated] to={to_number} body={body[:60]!r}")
        return "simulated"

    payload = urllib.parse.urlencode({
        "To": to_number if to_number.startswith("+") else "+1" + to_number,
        "From": config.TWILIO_FROM_NUMBER,
        "Body": body[:1500],
    }).encode()
    auth = base64.b64encode(
        f"{config.TWILIO_ACCOUNT_SID}:{config.TWILIO_AUTH_TOKEN}".encode()).decode()
    request = urllib.request.Request(
        TWILIO_URL.format(sid=urllib.parse.quote(config.TWILIO_ACCOUNT_SID)),
        data=payload,
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            json.loads(response.read().decode("utf-8"))
        repo.log_outbound(tenant_id, "sms", to_number, "", body, "sent", "", lead_id)
        return "sent"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        repo.log_outbound(tenant_id, "sms", to_number, "", body, "failed", detail, lead_id)
        print(f"[sms:failed] to={to_number}: {exc} {detail}")
        return "failed"
    except Exception as exc:
        repo.log_outbound(tenant_id, "sms", to_number, "", body, "failed", str(exc), lead_id)
        print(f"[sms:failed] to={to_number}: {exc}")
        return "failed"
