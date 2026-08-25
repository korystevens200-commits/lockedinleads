"""
Agency / admin API.

Only agency_admin users reach any of this — auth.require_agency() is the first
line of every handler. This is also where "view as client" is granted, and it
is recorded server-side on the session rather than accepted from the client.
"""

from .. import auth, config, db, metrics, repo, security
from ..billing import stripe_client
from ..db import now_ms
from ..http_util import HttpError, json_response
from ..settings_schema import DAYS
from . import router


@router.get("/api/admin/overview")
def overview(req):
    auth.require_agency(req)
    return json_response({
        "overview": metrics.agency_overview(),
        "plans": repo.list_plans(active_only=False),
        "health": _health(),
    })


def _health():
    """System health for the agency console — never exposes credential values."""
    checks = []
    try:
        db.query_one("SELECT 1 AS ok")
        checks.append({"name": "Database", "status": "ok", "detail": "SQLite reachable"})
    except Exception as exc:
        checks.append({"name": "Database", "status": "error", "detail": str(exc)[:120]})

    status = config.integration_status()
    checks.append({
        "name": "AI assistant",
        "status": "ok" if status["ai"]["configured"] else "degraded",
        "detail": (f"Live model: {status['ai']['model']}" if status["ai"]["configured"]
                   else "No API key — using the built-in conversation engine"),
    })
    checks.append({
        "name": "Email notifications",
        "status": "ok" if status["email"]["configured"] else "degraded",
        "detail": "SMTP configured" if status["email"]["configured"] else "Simulated (no SMTP configured)",
    })
    checks.append({
        "name": "SMS notifications",
        "status": "ok" if status["sms"]["configured"] else "degraded",
        "detail": "Twilio configured" if status["sms"]["configured"] else "Simulated (no Twilio configured)",
    })
    checks.append({
        "name": "Billing",
        "status": "ok" if status["billing"]["configured"] else "degraded",
        "detail": "Stripe connected" if status["billing"]["configured"] else "Mock mode (no Stripe key)",
    })
    checks.append({
        "name": "Automation worker",
        "status": "ok" if config.WORKER_ENABLED else "degraded",
        "detail": (f"Sweeping every {config.WORKER_INTERVAL_SECONDS}s"
                   if config.WORKER_ENABLED else "Disabled"),
    })

    pending = db.query_one(
        """SELECT COUNT(*) AS n FROM leads WHERE next_followup_at IS NOT NULL
           AND next_followup_at < ?""", (now_ms() - 10 * 60000,))
    overdue = int(pending["n"]) if pending else 0
    checks.append({
        "name": "Follow-up queue",
        "status": "ok" if overdue == 0 else "degraded",
        "detail": "Up to date" if overdue == 0 else f"{overdue} follow-up(s) more than 10 min overdue",
    })

    failures = db.query_one(
        "SELECT COUNT(*) AS n FROM outbound_log WHERE status = 'failed' AND created_at > ?",
        (now_ms() - 86400000,))
    failed = int(failures["n"]) if failures else 0
    if failed:
        checks.append({"name": "Outbound delivery", "status": "error",
                       "detail": f"{failed} failed send(s) in the last 24h"})

    worst = "ok"
    for check in checks:
        if check["status"] == "error":
            worst = "error"
            break
        if check["status"] == "degraded":
            worst = "degraded"
    return {"overall": worst, "checks": checks}


@router.get("/api/admin/clients")
def list_clients(req):
    auth.require_agency(req)
    return json_response({"clients": metrics.agency_overview()["clients"]})


@router.post("/api/admin/clients")
def create_client(req):
    auth.require_agency(req)
    body = req.json
    name = security.clean_text(body.get("name"), 120)
    if not name:
        raise HttpError(400, "Business name is required.")
    owner_email = security.clean_text(body.get("owner_email"), 254).lower()
    owner_password = body.get("owner_password") or ""
    if owner_email and not security.valid_email(owner_email):
        raise HttpError(400, "That owner email address doesn't look right.")
    if owner_email and len(owner_password) < 10:
        raise HttpError(400, "Set an owner password of at least 10 characters.")
    if owner_email and repo.get_user_by_email(owner_email):
        raise HttpError(409, "A user with that email already exists.")

    plan = repo.get_plan_by_slug(body.get("plan_slug") or "growth") or (repo.list_plans() or [None])[0]
    tenant = repo.create_tenant(
        name,
        industry=security.clean_text(body.get("industry"), 60) or "cleaning",
        timezone=security.clean_text(body.get("timezone"), 60) or "America/New_York",
        plan_id=plan["id"] if plan else None,
        contact_name=security.clean_text(body.get("contact_name"), 120),
        contact_email=owner_email or security.clean_text(body.get("contact_email"), 254),
        contact_phone=security.clean_text(body.get("contact_phone"), 32),
        website=security.clean_text(body.get("website"), 200),
    )
    if plan:
        repo.upsert_subscription(tenant["id"], plan["id"], status="trialing")

    owner = None
    if owner_email:
        owner = repo.create_user(owner_email, owner_password,
                                 security.clean_text(body.get("contact_name"), 120) or name,
                                 "owner", tenant["id"])
    repo.log_activity(tenant["id"], "account", f"Account created by {auth.require_user(req)['email']}")
    return json_response({"tenant": repo.get_tenant(tenant["id"]),
                          "owner_id": owner["id"] if owner else None}, 201)


@router.get("/api/admin/clients/<tenant_id>")
def client_detail(req, tenant_id):
    auth.require_agency(req)
    tenant = repo.get_tenant(tenant_id)
    if not tenant:
        raise HttpError(404, "Client not found.")
    return json_response({
        "tenant": tenant,
        "summary": metrics.summary(tenant_id, 30),
        "users": repo.list_users(tenant_id),
        "subscription": repo.get_subscription(tenant_id),
        "services": repo.list_services(tenant_id, active_only=False),
        "areas": repo.list_service_areas(tenant_id),
        "recent_leads": repo.list_leads(tenant_id, limit=10),
        "activity": repo.list_activity(tenant_id, 15),
    })


@router.patch("/api/admin/clients/<tenant_id>")
def update_client(req, tenant_id):
    auth.require_agency(req)
    tenant = repo.get_tenant(tenant_id)
    if not tenant:
        raise HttpError(404, "Client not found.")
    body = req.json
    patch = {}
    for key, max_len in (("name", 120), ("industry", 60), ("timezone", 60), ("contact_name", 120),
                         ("contact_email", 254), ("contact_phone", 32), ("website", 200)):
        if key in body:
            patch[key] = security.clean_text(body[key], max_len)
    if body.get("status") in ("onboarding", "active", "paused", "cancelled"):
        patch["status"] = body["status"]
    if patch:
        repo.update_tenant(tenant_id, patch)
    if body.get("plan_slug"):
        plan = repo.get_plan_by_slug(body["plan_slug"])
        if not plan:
            raise HttpError(400, "Unknown plan.")
        sub = repo.get_subscription(tenant_id)
        repo.upsert_subscription(tenant_id, plan["id"],
                                 status=(sub or {}).get("status", "trialing"))
    return json_response({"tenant": repo.get_tenant(tenant_id)})


@router.post("/api/admin/clients/<tenant_id>/users")
def add_client_user(req, tenant_id):
    auth.require_agency(req)
    if not repo.get_tenant(tenant_id):
        raise HttpError(404, "Client not found.")
    body = req.json
    email = security.clean_text(body.get("email"), 254).lower()
    password = body.get("password") or ""
    role = body.get("role") if body.get("role") in ("owner", "staff") else "owner"
    if not security.valid_email(email):
        raise HttpError(400, "A valid email address is required.")
    if len(password) < 10:
        raise HttpError(400, "Password must be at least 10 characters.")
    try:
        user = repo.create_user(email, password, security.clean_text(body.get("name"), 120),
                                role, tenant_id)
    except ValueError as exc:
        raise HttpError(409, str(exc)) from exc
    return json_response({"user": {k: user[k] for k in ("id", "email", "name", "role")}}, 201)


@router.post("/api/admin/impersonate")
def impersonate(req):
    """Open a client's account. The chosen tenant is written to the session row,
    so the client-facing endpoints keep enforcing a single tenant per request."""
    auth.require_agency(req)
    tenant_id = req.json.get("tenant_id")
    if tenant_id:
        tenant = repo.get_tenant(tenant_id)
        if not tenant:
            raise HttpError(404, "Client not found.")
        repo.set_acting_tenant(req.session_token, tenant_id)
        return json_response({"acting_tenant": {"id": tenant["id"], "name": tenant["name"],
                                                "slug": tenant["slug"]}})
    repo.set_acting_tenant(req.session_token, None)
    return json_response({"acting_tenant": None})


@router.get("/api/admin/plans")
def list_plans(req):
    auth.require_agency(req)
    return json_response({"plans": repo.list_plans(active_only=False),
                          "stripe": stripe_client.publishable_config()})


@router.post("/api/admin/plans")
def create_plan(req):
    auth.require_agency(req)
    body = req.json
    name = security.clean_text(body.get("name"), 60)
    if not name:
        raise HttpError(400, "Plan name is required.")
    slug = security.slugify(body.get("slug") or name)
    if repo.get_plan_by_slug(slug):
        raise HttpError(409, "A plan with that name already exists.")
    plan = repo.upsert_plan(
        slug=slug, name=name,
        setup_cents=security.clamp_int(body.get("setup_cents"), 0, 100_000_00, 0),
        monthly_cents=security.clamp_int(body.get("monthly_cents"), 0, 100_000_00, 0),
        features=[security.clean_text(f, 120) for f in (body.get("features") or [])[:12]],
        highlight=bool(body.get("highlight")),
        sort_order=security.clamp_int(body.get("sort_order"), 0, 99, 10))
    return json_response({"plan": plan}, 201)


@router.patch("/api/admin/plans/<plan_id>")
def update_plan(req, plan_id):
    auth.require_agency(req)
    if not repo.get_plan(plan_id):
        raise HttpError(404, "Plan not found.")
    body = dict(req.json)
    for key in ("stripe_price_id", "stripe_setup_price_id"):
        if key in body:
            body[key] = security.clean_text(body[key], 80)
    if "name" in body:
        body["name"] = security.clean_text(body["name"], 60)
    return json_response({"plan": repo.update_plan(plan_id, body)})


@router.get("/api/admin/health")
def health(req):
    auth.require_agency(req)
    return json_response(_health())


@router.get("/api/admin/timezones")
def timezones(req):
    auth.require_agency(req)
    from zoneinfo import available_timezones
    common = sorted(tz for tz in available_timezones()
                    if tz.startswith(("America/", "US/", "Europe/", "Australia/", "Pacific/")))
    return json_response({"timezones": common, "days": DAYS})
