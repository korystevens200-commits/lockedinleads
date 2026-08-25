"""
Public endpoints — no session required.

These are the only routes an unauthenticated visitor can reach, so each one is
rate-limited, validates its input, and is careful never to leak data about a
business beyond what its own website already shows.
"""

from .. import config, repo, security
from ..ai import engine
from ..billing import stripe_client
from ..db import now_ms
from ..http_util import HttpError, error_response, json_response
from ..integrations.normalize import normalize
from . import router

CHAT_TOKEN_PREFIX = "chat:"


def _rate_limit(req, bucket, limit, window):
    if not security.limiter.check(f"{bucket}:{req.remote_ip}", limit, window):
        raise HttpError(429, "Too many requests. Please slow down.", code="rate_limited")


@router.get("/api/public/config")
def public_config(req):
    """Pricing and copy for the marketing site. No secrets, no client data."""
    plans = [{
        "slug": p["slug"], "name": p["name"], "setup_price": p["setup_price"],
        "monthly_price": p["monthly_price"], "features": p["features"],
        "highlight": p["highlight"],
    } for p in repo.list_plans()]
    demo = repo.get_tenant_by_slug("demo")
    return json_response({
        "app_name": config.AGENCY_NAME,
        "plans": plans,
        "demo_slug": demo["slug"] if demo else None,
        "booking_url": config.DEMO_BOOKING_URL,
        "contact_email": config.CONTACT_EMAIL,
    })


@router.post("/api/public/leads/<slug>")
def public_lead_form(req, slug):
    """Drop-in endpoint for a business's own website form."""
    _rate_limit(req, "public_lead", 20, 300)
    tenant = repo.get_tenant_by_slug(slug)
    if not tenant or tenant["status"] in ("cancelled",):
        raise HttpError(404, "Unknown business.")

    lead_data, error = normalize(req.json, default_source="website_form")
    if error:
        repo.log_webhook_event(tenant["id"], "website_form", "rejected", error,
                               remote_ip=req.remote_ip)
        raise HttpError(400, error)

    lead = _ingest(tenant, lead_data, req)
    return json_response({"ok": True, "lead_id": lead["id"]}, 201)


def _ingest(tenant, lead_data, req, source_label="website_form"):
    """Create (or update) a lead and fire the instant response."""
    existing = (repo.find_lead_by_external_id(tenant["id"], lead_data.get("external_id"))
                or repo.find_lead_by_contact(tenant["id"], lead_data.get("phone"),
                                             lead_data.get("email")))
    if existing and existing["status"] not in ("LOST", "CUSTOMER"):
        # A repeat enquiry re-opens the same conversation instead of spawning a
        # duplicate the owner has to reconcile later.
        repo.log_activity(tenant["id"], "lead_repeat",
                          "Repeat enquiry matched to an existing lead", existing["id"])
        repo.log_webhook_event(tenant["id"], lead_data.get("source", source_label), "accepted",
                               "matched existing lead", existing["id"], remote_ip=req.remote_ip)
        if existing["opted_out"]:
            return existing
        engine.handle_inbound(tenant, existing,
                              lead_data.get("notes") or "Sent another enquiry through the form.")
        return existing

    lead = repo.create_lead(tenant["id"], lead_data)
    repo.log_webhook_event(tenant["id"], lead_data.get("source", source_label), "accepted",
                           "", lead["id"], remote_ip=req.remote_ip)
    engine.handle_new_lead(tenant, lead)
    return repo.get_lead(tenant["id"], lead["id"])


@router.post("/api/webhooks/leads")
def webhook_leads(req):
    """Authenticated by a per-tenant API key. The key identifies the tenant, so
    a payload can never be routed to a business that did not issue the key."""
    _rate_limit(req, "webhook", 120, 60)
    api_key = (req.header("X-API-Key") or "").strip()
    if not api_key:
        auth = req.header("Authorization") or ""
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    tenant = repo.tenant_for_api_key(api_key)
    if not tenant:
        repo.log_webhook_event(None, "unknown", "rejected", "invalid API key",
                               remote_ip=req.remote_ip)
        raise HttpError(401, "Invalid or missing API key.", code="invalid_api_key")
    if tenant["status"] in ("paused", "cancelled"):
        raise HttpError(403, "This account is not active.", code="account_inactive")

    lead_data, error = normalize(req.json, default_source="webhook")
    if error:
        repo.log_webhook_event(tenant["id"], "webhook", "rejected", error,
                               payload_excerpt=str(req.raw_body[:300]), remote_ip=req.remote_ip)
        raise HttpError(400, error)

    lead = _ingest(tenant, lead_data, req, "webhook")
    return json_response({"ok": True, "lead_id": lead["id"], "status": lead["status"]}, 201)


@router.post("/api/webhooks/stripe")
def webhook_stripe(req):
    ok, reason = stripe_client.verify_webhook_signature(
        req.raw_body, req.header("Stripe-Signature"))
    if not ok:
        return error_response(400, f"Signature verification failed: {reason}")
    try:
        result = stripe_client.apply_webhook_event(req.json)
    except Exception as exc:
        return error_response(400, f"Could not apply event: {exc}")
    return json_response({"ok": True, "result": result})


# ------------------------------------------------------------ chat widget ---

def _chat_token(lead_id):
    return security.sign_value(CHAT_TOKEN_PREFIX + lead_id, config.SECRET_KEY)


def _lead_from_chat_token(token):
    value = security.unsign_value(token or "", config.SECRET_KEY)
    if not value or not value.startswith(CHAT_TOKEN_PREFIX):
        return None, None
    lead_id = value[len(CHAT_TOKEN_PREFIX):]
    row = repo.db.query_one("SELECT tenant_id FROM leads WHERE id = ?", (lead_id,))
    if not row:
        return None, None
    tenant = repo.get_tenant(row["tenant_id"])
    return tenant, repo.get_lead(row["tenant_id"], lead_id)


def _serialize_messages(messages):
    return [{"id": m["id"], "role": m["role"], "body": m["body"],
             "created_at": m["created_at"],
             "offered_slots": bool((m.get("meta") or {}).get("offered_slots"))}
            for m in messages if m["role"] in ("lead", "ai", "human")]


@router.post("/api/chat/<slug>/start")
def chat_start(req, slug):
    """Opens a conversation from a business's website chat widget."""
    _rate_limit(req, "chat_start", 15, 300)
    tenant = repo.get_tenant_by_slug(slug)
    if not tenant or tenant["status"] == "cancelled":
        raise HttpError(404, "Unknown business.")

    body = req.json
    lead = repo.create_lead(tenant["id"], {
        "name": security.clean_text(body.get("name"), 120),
        "phone": security.clean_text(body.get("phone"), 32),
        "email": security.clean_text(body.get("email"), 254).lower(),
        "service_requested": security.clean_text(body.get("service"), 120),
        "source": "chat_widget",
        "consent": bool(body.get("consent")),
    })
    engine.handle_new_lead(tenant, lead)
    messages = repo.list_messages(tenant["id"], lead["id"])
    return json_response({
        "token": _chat_token(lead["id"]),
        "business": {"name": tenant["name"],
                     "assistant": tenant["settings"]["ai"]["assistant_name"]},
        "messages": _serialize_messages(messages),
    }, 201)


@router.post("/api/chat/message")
def chat_message(req):
    _rate_limit(req, "chat_msg", 60, 300)
    body = req.json
    tenant, lead = _lead_from_chat_token(body.get("token"))
    if not tenant or not lead:
        raise HttpError(401, "This conversation has expired. Please start a new one.")
    text = security.clean_text(body.get("text"), 2000)
    if not text:
        raise HttpError(400, "Message cannot be empty.")
    if lead["opted_out"]:
        raise HttpError(403, "This conversation has been closed.")

    engine.handle_inbound(tenant, lead, text, channel="chat")
    messages = repo.list_messages(tenant["id"], lead["id"])
    lead = repo.get_lead(tenant["id"], lead["id"])
    return json_response({
        "messages": _serialize_messages(messages),
        "status": lead["status"],
        "ai_active": lead["ai_active"],
    })


@router.get("/api/chat/messages")
def chat_poll(req):
    """Lets the widget pick up a human reply sent from the dashboard."""
    tenant, lead = _lead_from_chat_token(req.q("token"))
    if not tenant or not lead:
        raise HttpError(401, "This conversation has expired.")
    return json_response({
        "messages": _serialize_messages(repo.list_messages(tenant["id"], lead["id"])),
        "status": lead["status"],
        "ai_active": lead["ai_active"],
        "server_time": now_ms(),
    })
