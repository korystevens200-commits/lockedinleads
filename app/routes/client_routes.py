"""
Client (business owner) API.

Every handler calls auth.resolve_tenant() first: that is the single point where
a request is bound to exactly one business's data.
"""

from .. import auth, metrics, repo, security
from ..ai import engine, prompt
from ..ai.provider import get_provider
from ..automation import schedule
from ..db import now_ms
from ..http_util import HttpError, json_response, no_content
from . import router

HOUR_MS = 3600000


def _tenant(req, lead_id=None):
    tenant_id = auth.resolve_tenant(req)
    tenant = repo.get_tenant(tenant_id)
    if not tenant:
        raise HttpError(404, "Account not found.")
    if lead_id is None:
        return tenant, None
    lead = repo.get_lead(tenant_id, lead_id)
    if not lead:
        raise HttpError(404, "Lead not found.")
    return tenant, lead


def _days(req, default=30):
    return security.clamp_int(req.q("days", default), 0, 365, default)


# ------------------------------------------------------------- dashboard ----

@router.get("/api/dashboard")
def dashboard(req):
    tenant, _ = _tenant(req)
    days = _days(req)
    return json_response({
        "tenant": {"id": tenant["id"], "name": tenant["name"], "slug": tenant["slug"],
                   "status": tenant["status"], "timezone": tenant["timezone"],
                   "is_demo": tenant["is_demo"], "onboarding_step": tenant["onboarding_step"],
                   "onboarded_at": tenant["onboarded_at"]},
        "summary": metrics.summary(tenant["id"], days),
        "recent_leads": repo.list_leads(tenant["id"], limit=8),
        "activity": repo.list_activity(tenant["id"], 12),
        "upcoming_appointments": _upcoming(tenant),
        "unread_notifications": len(repo.list_notifications(tenant["id"], unread_only=True)),
    })


def _upcoming(tenant, limit=5):
    appointments = repo.list_appointments(tenant["id"], since=now_ms(), limit=limit)
    out = []
    for appt in appointments:
        if appt["status"] == "cancelled":
            continue
        lead = repo.get_lead(tenant["id"], appt["lead_id"])
        out.append({**appt,
                    "when": schedule.format_slot(appt["starts_at"], tenant),
                    "lead_name": (lead or {}).get("name") or "Unnamed lead",
                    "lead_phone": (lead or {}).get("phone") or ""})
    return out


@router.get("/api/reports")
def reports(req):
    tenant, _ = _tenant(req)
    days = _days(req)
    return json_response({
        "summary": metrics.summary(tenant["id"], days),
        "timeseries": metrics.timeseries(tenant["id"], min(days or 30, 90)),
        "sources": metrics.source_breakdown(tenant["id"], days),
        "range_days": days,
    })


@router.get("/api/activity")
def activity(req):
    tenant, _ = _tenant(req)
    return json_response({"activity": repo.list_activity(
        tenant["id"], security.clamp_int(req.q("limit", 30), 1, 100, 30))})


@router.get("/api/notifications")
def notifications(req):
    tenant, _ = _tenant(req)
    return json_response({"notifications": repo.list_notifications(tenant["id"], limit=40)})


@router.post("/api/notifications/read")
def read_notifications(req):
    tenant, _ = _tenant(req)
    repo.mark_notifications_read(tenant["id"])
    return json_response({"ok": True})


# ----------------------------------------------------------------- leads ----

@router.get("/api/leads")
def list_leads(req):
    tenant, _ = _tenant(req)
    leads = repo.list_leads(
        tenant["id"], status=req.q("status"), search=req.q("q"), source=req.q("source"),
        limit=security.clamp_int(req.q("limit", 200), 1, 500, 200),
        offset=security.clamp_int(req.q("offset", 0), 0, 100000, 0))
    return json_response({"leads": leads, "counts": metrics.lead_counts(tenant["id"])})


@router.post("/api/leads")
def create_lead(req):
    tenant, _ = _tenant(req)
    body = req.json
    name = security.clean_text(body.get("name"), 120)
    phone = security.clean_text(body.get("phone"), 32)
    email = security.clean_text(body.get("email"), 254).lower()
    if not (name or phone or email):
        raise HttpError(400, "Add at least a name, phone number or email address.")
    if phone and not security.valid_phone(phone):
        raise HttpError(400, "That phone number doesn't look right.")
    if email and not security.valid_email(email):
        raise HttpError(400, "That email address doesn't look right.")

    duplicate = repo.find_lead_by_contact(tenant["id"], phone, email)
    if duplicate and duplicate["status"] not in ("LOST", "CUSTOMER"):
        raise HttpError(409, f"{duplicate['name'] or 'A lead'} with that contact info already exists.",
                        code="duplicate_lead", extra={"lead_id": duplicate["id"]})

    lead = repo.create_lead(tenant["id"], {
        "name": name, "phone": phone, "email": email,
        "source": body.get("source") or "manual",
        "service_requested": security.clean_text(body.get("service_requested"), 120),
        "location": security.clean_text(body.get("location"), 160),
        "notes": security.clean_text(body.get("notes"), 2000),
        "consent": bool(body.get("consent")),
        "ai_active": body.get("ai_active", True),
    })
    if body.get("start_ai", True):
        engine.handle_new_lead(tenant, lead)
    return json_response({"lead": repo.get_lead(tenant["id"], lead["id"])}, 201)


@router.get("/api/leads/<lead_id>")
def get_lead(req, lead_id):
    tenant, lead = _tenant(req, lead_id)
    return json_response({
        "lead": lead,
        "messages": repo.list_messages(tenant["id"], lead_id),
        "appointments": repo.list_appointments(tenant["id"], lead_id=lead_id),
        "questions": repo.list_questions(tenant["id"]),
        "next_followup_label": (schedule.format_slot(lead["next_followup_at"], tenant)
                                if lead["next_followup_at"] else None),
    })


@router.patch("/api/leads/<lead_id>")
def update_lead(req, lead_id):
    tenant, lead = _tenant(req, lead_id)
    body = req.json
    patch = {}
    for key in ("name", "phone", "email", "service_requested", "location", "notes",
                "status", "score", "close_reason", "source"):
        if key in body:
            patch[key] = security.clean_text(body[key], 2000 if key == "notes" else 254)
    if "estimated_value" in body:
        try:
            patch["estimated_value"] = max(0.0, float(body["estimated_value"]))
        except (TypeError, ValueError):
            raise HttpError(400, "Estimated value must be a number.")
    if patch.get("status") and patch["status"] not in repo.LEAD_STATUSES:
        raise HttpError(400, "Unknown status.")

    was_status = lead["status"]
    updated = repo.update_lead(tenant["id"], lead_id, patch)
    if patch.get("status") and patch["status"] != was_status:
        repo.log_activity(tenant["id"], "status_change",
                          f"Status changed from {was_status} to {patch['status']}", lead_id)
        if patch["status"] in ("LOST", "CUSTOMER", "BOOKED"):
            repo.update_lead(tenant["id"], lead_id, {"next_followup_at": None})
    return json_response({"lead": repo.get_lead(tenant["id"], lead_id)})


@router.get("/api/leads/<lead_id>/messages")
def lead_messages(req, lead_id):
    tenant, _ = _tenant(req, lead_id)
    return json_response({"messages": repo.list_messages(tenant["id"], lead_id)})


@router.post("/api/leads/<lead_id>/messages")
def send_message(req, lead_id):
    """Owner replies by hand — this switches the conversation to human control."""
    tenant, lead = _tenant(req, lead_id)
    user = auth.require_user(req)
    body = security.clean_text(req.json.get("body"), 2000)
    if not body:
        raise HttpError(400, "Message cannot be empty.")
    if lead["opted_out"]:
        raise HttpError(403, "This lead opted out of messages.")
    message = engine.send_human_message(tenant, lead, body, user["name"] or user["email"])
    return json_response({"message": message,
                          "lead": repo.get_lead(tenant["id"], lead_id)}, 201)


@router.post("/api/leads/<lead_id>/ai")
def toggle_ai(req, lead_id):
    tenant, lead = _tenant(req, lead_id)
    active = bool(req.json.get("active"))
    if active and lead["opted_out"]:
        raise HttpError(400, "This lead opted out — the assistant cannot be re-enabled.")
    updated = engine.set_ai_active(tenant, lead, active)
    return json_response({"lead": updated})


@router.post("/api/leads/<lead_id>/followup")
def followup_now(req, lead_id):
    tenant, lead = _tenant(req, lead_id)
    if lead["opted_out"]:
        raise HttpError(400, "This lead opted out of messages.")
    messages = engine.run_followup(tenant, {**lead, "ai_active": True})
    if not messages:
        raise HttpError(400, "No follow-up was sent — the sequence is finished or this lead is closed.")
    return json_response({"messages": messages, "lead": repo.get_lead(tenant["id"], lead_id)})


@router.post("/api/leads/<lead_id>/simulate")
def simulate_reply(req, lead_id):
    """Plays a customer reply through the real engine — used by the demo account
    and to sanity-check settings changes without messaging anyone."""
    tenant, lead = _tenant(req, lead_id)
    text = security.clean_text(req.json.get("text"), 2000)
    if not text:
        raise HttpError(400, "Enter a message to simulate.")
    engine.handle_inbound(tenant, lead, text, channel="chat")
    return json_response({"messages": repo.list_messages(tenant["id"], lead_id),
                          "lead": repo.get_lead(tenant["id"], lead_id)})


@router.get("/api/leads/<lead_id>/slots")
def lead_slots(req, lead_id):
    tenant, _ = _tenant(req, lead_id)
    slots = schedule.open_slots(tenant, count=security.clamp_int(req.q("count", 6), 1, 20, 6))
    return json_response({"slots": slots})


@router.post("/api/leads/<lead_id>/appointments")
def book_appointment(req, lead_id):
    tenant, lead = _tenant(req, lead_id)
    body = req.json
    try:
        starts_at = int(body.get("starts_at"))
    except (TypeError, ValueError):
        raise HttpError(400, "Pick a start time.")
    duration = security.clamp_int(body.get("duration_minutes"),
                                  15, 960, tenant["settings"]["booking"]["slot_minutes"])
    ends_at = int(body.get("ends_at") or (starts_at + duration * 60000))
    try:
        appointment = engine.book_manually(
            tenant, lead, starts_at, ends_at,
            service=security.clean_text(body.get("service"), 120),
            notes=security.clean_text(body.get("notes"), 500))
    except ValueError as exc:
        raise HttpError(409, str(exc)) from exc
    return json_response({"appointment": appointment,
                          "lead": repo.get_lead(tenant["id"], lead_id)}, 201)


@router.get("/api/appointments")
def list_appointments(req):
    tenant, _ = _tenant(req)
    days = security.clamp_int(req.q("days", 30), 1, 365, 30)
    appointments = repo.list_appointments(tenant["id"], since=now_ms() - 7 * 24 * HOUR_MS,
                                          until=now_ms() + days * 24 * HOUR_MS, limit=200)
    out = []
    for appt in appointments:
        lead = repo.get_lead(tenant["id"], appt["lead_id"])
        out.append({**appt, "when": schedule.format_slot(appt["starts_at"], tenant),
                    "lead_name": (lead or {}).get("name") or "Unnamed lead",
                    "lead_phone": (lead or {}).get("phone") or "",
                    "lead_id": appt["lead_id"]})
    return json_response({"appointments": out})


@router.patch("/api/appointments/<appointment_id>")
def update_appointment(req, appointment_id):
    tenant, _ = _tenant(req)
    body = req.json
    patch = {}
    if body.get("status") in ("scheduled", "completed", "cancelled", "no_show"):
        patch["status"] = body["status"]
    if "notes" in body:
        patch["notes"] = security.clean_text(body["notes"], 500)
    if not patch:
        raise HttpError(400, "Nothing to update.")
    appointment = repo.update_appointment(tenant["id"], appointment_id, patch)
    if not appointment:
        raise HttpError(404, "Appointment not found.")
    if patch.get("status") == "completed":
        repo.update_lead(tenant["id"], appointment["lead_id"], {"status": "CUSTOMER"})
        repo.log_activity(tenant["id"], "customer", "Appointment completed — lead marked as customer",
                          appointment["lead_id"])
    elif patch.get("status") == "cancelled":
        repo.log_activity(tenant["id"], "cancelled", "Appointment cancelled",
                          appointment["lead_id"])
    return json_response({"appointment": appointment})


# ---------------------------------------------------- settings / config -----

def _config_payload(tenant):
    return {
        "business": {
            "name": tenant["name"], "industry": tenant["industry"], "timezone": tenant["timezone"],
            "contact_name": tenant["contact_name"], "contact_email": tenant["contact_email"],
            "contact_phone": tenant["contact_phone"], "website": tenant["website"],
            "address": tenant["address"], "slug": tenant["slug"], "status": tenant["status"],
            "onboarding_step": tenant["onboarding_step"], "onboarded_at": tenant["onboarded_at"],
        },
        "settings": tenant["settings"],
        "services": repo.list_services(tenant["id"], active_only=False),
        "areas": repo.list_service_areas(tenant["id"]),
        "questions": repo.list_questions(tenant["id"]),
        "hours_summary": schedule.humanize_hours(tenant),
        "sample_slots": schedule.open_slots(tenant, count=3),
    }


@router.get("/api/settings")
def get_settings(req):
    tenant, _ = _tenant(req)
    return json_response(_config_payload(tenant))


@router.patch("/api/settings")
def patch_settings(req):
    tenant, _ = _tenant(req)
    body = req.json

    business = body.get("business") or {}
    tenant_patch = {}
    for key, max_len in (("name", 120), ("industry", 60), ("timezone", 60), ("contact_name", 120),
                         ("contact_email", 254), ("contact_phone", 32), ("website", 200),
                         ("address", 240)):
        if key in business:
            tenant_patch[key] = security.clean_text(business[key], max_len)
    if tenant_patch.get("contact_email") and not security.valid_email(tenant_patch["contact_email"]):
        raise HttpError(400, "That notification email address doesn't look right.")
    if tenant_patch.get("timezone"):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tenant_patch["timezone"])
        except Exception:
            raise HttpError(400, "Unknown timezone. Use an IANA name like America/New_York.")
    if tenant_patch:
        repo.update_tenant(tenant["id"], tenant_patch)

    if isinstance(body.get("settings"), dict):
        repo.update_tenant_settings(tenant["id"], body["settings"])
    if isinstance(body.get("services"), list):
        repo.replace_services(tenant["id"], body["services"])
    if isinstance(body.get("areas"), list):
        repo.replace_service_areas(tenant["id"], body["areas"])
    if isinstance(body.get("questions"), list):
        repo.replace_questions(tenant["id"], body["questions"])

    return json_response(_config_payload(repo.get_tenant(tenant["id"])))


# ------------------------------------------------------------- onboarding ---

MAX_ONBOARDING_STEP = 7


@router.post("/api/onboarding/step")
def onboarding_step(req):
    tenant, _ = _tenant(req)
    step = security.clamp_int(req.json.get("step"), 1, MAX_ONBOARDING_STEP, 1)
    repo.update_tenant(tenant["id"], {"onboarding_step": step})
    return json_response({"onboarding_step": step})


@router.post("/api/onboarding/complete")
def onboarding_complete(req):
    tenant, _ = _tenant(req)
    if not repo.list_services(tenant["id"]):
        raise HttpError(400, "Add at least one service before finishing setup.")
    if not repo.list_service_areas(tenant["id"]):
        raise HttpError(400, "Add at least one service area before finishing setup.")
    repo.update_tenant(tenant["id"], {
        "onboarding_step": MAX_ONBOARDING_STEP, "onboarded_at": now_ms(),
        "status": "active" if tenant["status"] == "onboarding" else tenant["status"]})
    repo.log_activity(tenant["id"], "onboarding", "Setup completed — the system is live")
    return json_response({"ok": True, "tenant": repo.get_tenant(tenant["id"])})


@router.post("/api/ai/test")
def test_ai(req):
    """Dry-run the assistant against the saved configuration. Nothing is stored
    and no message is sent — this is the onboarding 'test conversation' step."""
    tenant, _ = _tenant(req)
    body = req.json
    history = []
    for item in (body.get("history") or [])[:20]:
        role = item.get("role")
        text = security.clean_text(item.get("body"), 1000)
        if role in ("lead", "ai") and text:
            history.append({"role": role, "body": text, "meta": item.get("meta") or {},
                            "created_at": now_ms()})
    incoming = security.clean_text(body.get("text"), 1000)

    fake_lead = {
        "id": "preview", "tenant_id": tenant["id"],
        "name": security.clean_text(body.get("name"), 120) or "Test Lead",
        "phone": "", "email": "", "source": "manual", "source_label": "Manual entry",
        "service_requested": security.clean_text(body.get("service"), 120),
        "location": "", "status": "NEW", "score": "unscored",
        "qualification": body.get("qualification") or {}, "followup_count": 0,
        "created_at": now_ms(), "ai_active": True, "opted_out": False,
    }
    slots = schedule.open_slots(tenant, count=3)
    ctx = prompt.build_context(tenant, fake_lead, history, slots=slots)
    provider = get_provider()
    turn = provider.generate(ctx, "opening" if not history else "reply", incoming=incoming or None)
    if turn.error or not turn.reply:
        from ..ai.rules_provider import RulesProvider
        turn = RulesProvider().generate(ctx, "opening" if not history else "reply",
                                        incoming=incoming or None)
    return json_response({
        "reply": turn.reply,
        "intent": turn.intent,
        "qualified": turn.qualified,
        "provider": turn.provider,
        "qualification_updates": turn.qualification_updates,
        "meta": {"pending_key": turn.pending_key, "offered_slots": turn.offered_slots},
        "slots": slots,
    })


# --------------------------------------------------------------- api keys ---

@router.get("/api/api-keys")
def list_keys(req):
    tenant, _ = _tenant(req)
    from .. import config as cfg
    return json_response({
        "keys": repo.list_api_keys(tenant["id"]),
        "webhook_url": f"{cfg.PUBLIC_URL}/api/webhooks/leads",
        "form_url": f"{cfg.PUBLIC_URL}/api/public/leads/{tenant['slug']}",
        "chat_url": f"{cfg.PUBLIC_URL}/chat.html?b={tenant['slug']}",
        "recent_events": repo.list_webhook_events(tenant["id"], 10),
    })


@router.post("/api/api-keys")
def create_key(req):
    tenant, _ = _tenant(req)
    user = auth.require_user(req)
    if user["role"] == "staff":
        raise HttpError(403, "Only the account owner can create API keys.")
    label = security.clean_text(req.json.get("label"), 60) or "Default"
    key = repo.create_api_key(tenant["id"], label)
    repo.log_activity(tenant["id"], "api_key", f"API key created: {label}")
    # Returned exactly once — only the hash is stored.
    return json_response({"key": key, "note": "Copy this now — it is not shown again."}, 201)


@router.delete("/api/api-keys/<key_id>")
def revoke_key(req, key_id):
    tenant, _ = _tenant(req)
    repo.revoke_api_key(tenant["id"], key_id)
    repo.log_activity(tenant["id"], "api_key", "API key revoked")
    return no_content()


@router.get("/api/outbound")
def outbound_log(req):
    tenant, _ = _tenant(req)
    return json_response({"outbound": repo.list_outbound(tenant["id"], 30)})
