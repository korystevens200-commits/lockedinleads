"""Billing endpoints for the client app."""

from .. import auth, repo
from ..billing import stripe_client
from ..http_util import HttpError, json_response
from . import router


@router.get("/api/billing")
def get_billing(req):
    tenant_id = auth.resolve_tenant(req)
    tenant = repo.get_tenant(tenant_id)
    subscription = repo.get_subscription(tenant_id)
    return json_response({
        "subscription": subscription,
        "plans": repo.list_plans(),
        "stripe": stripe_client.publishable_config(),
        "tenant_status": tenant["status"],
    })


@router.post("/api/billing/checkout")
def start_checkout(req):
    tenant_id = auth.resolve_tenant(req)
    user = auth.require_user(req)
    if user["role"] == "staff":
        raise HttpError(403, "Only the account owner can manage billing.")

    tenant = repo.get_tenant(tenant_id)
    body = req.json
    plan = repo.get_plan_by_slug(body.get("plan_slug") or "")
    if not plan or not plan["active"]:
        raise HttpError(400, "Choose a valid plan.")
    kind = body.get("kind") if body.get("kind") in ("subscription", "setup") else "subscription"
    try:
        result = stripe_client.start_checkout(tenant, plan, kind)
    except stripe_client.StripeError as exc:
        raise HttpError(502, str(exc)) from exc
    return json_response(result)
