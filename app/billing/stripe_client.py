"""
Stripe integration.

Talks to Stripe's REST API over urllib — one dependency fewer. With no
STRIPE_SECRET_KEY the module runs in mock mode: it returns clearly-labelled
fake checkout sessions and records the subscription locally, so the billing
flow is testable end-to-end before Stripe is connected.

The secret key never leaves the server; only the publishable key is exposed,
and only through an authenticated endpoint.
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import config, repo
from ..db import now_ms

API_BASE = "https://api.stripe.com/v1"


class StripeError(Exception):
    pass


def _request(path, data=None, method="POST"):
    if not config.stripe_configured():
        raise StripeError("Stripe is not configured on this server.")
    url = f"{API_BASE}/{path.lstrip('/')}"
    body = urllib.parse.urlencode(_flatten_params(data or {}), doseq=True).encode() if data else None
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {config.STRIPE_SECRET_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": "2024-06-20",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise StripeError(f"Stripe API error {exc.code}: {detail}") from exc
    except Exception as exc:
        raise StripeError(f"Could not reach Stripe: {exc}") from exc


def _flatten_params(data, prefix=""):
    """Stripe wants bracketed form encoding: line_items[0][price]=..."""
    out = []
    for key, value in data.items():
        full = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten_params(value, full))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out.extend(_flatten_params(item, f"{full}[{i}]"))
                else:
                    out.append((f"{full}[{i}]", item))
        elif value is not None:
            out.append((full, value))
    return out


def publishable_config():
    """Safe to hand to an authenticated browser session."""
    return {
        "configured": config.stripe_configured(),
        "publishable_key": config.STRIPE_PUBLISHABLE_KEY,
        "mode": "live" if config.stripe_configured() else "mock",
    }


def start_checkout(tenant, plan, kind="subscription", success_url=None, cancel_url=None):
    """kind: 'subscription' (monthly) or 'setup' (one-time onboarding fee)."""
    success_url = success_url or f"{config.PUBLIC_URL}/app/billing.html?checkout=success"
    cancel_url = cancel_url or f"{config.PUBLIC_URL}/app/billing.html?checkout=cancelled"

    if not config.stripe_configured():
        # Mock mode: record the intent locally and hand back a labelled URL.
        repo.upsert_subscription(
            tenant["id"], plan["id"],
            status="active" if kind == "subscription" else (
                repo.get_subscription(tenant["id"]) or {}).get("status", "trialing"),
            setup_paid=True if kind == "setup" else bool(
                (repo.get_subscription(tenant["id"]) or {}).get("setup_paid")),
            current_period_end=now_ms() + 30 * 86400000 if kind == "subscription" else None)
        repo.log_activity(tenant["id"], "billing",
                          f"{kind.title()} recorded in mock mode (Stripe not configured)")
        return {"mock": True, "url": f"{success_url}&mock=1",
                "message": "Stripe is not configured — recorded locally in development mode."}

    price_id = plan.get("stripe_setup_price_id") if kind == "setup" else plan.get("stripe_price_id")
    if not price_id:
        raise StripeError(
            f"No Stripe price is set for the {plan['name']} plan's {kind} charge. "
            "Add it in the agency console under Plans.")

    sub = repo.get_subscription(tenant["id"])
    customer_id = (sub or {}).get("stripe_customer_id") or ""
    if not customer_id:
        customer = _request("customers", {
            "name": tenant["name"],
            "email": tenant.get("contact_email") or "",
            "metadata": {"tenant_id": tenant["id"], "tenant_slug": tenant["slug"]},
        })
        customer_id = customer["id"]
        repo.upsert_subscription(tenant["id"], plan["id"],
                                 status=(sub or {}).get("status", "trialing"),
                                 stripe_customer_id=customer_id)

    session = _request("checkout/sessions", {
        "mode": "subscription" if kind == "subscription" else "payment",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": tenant["id"],
        "metadata": {"tenant_id": tenant["id"], "plan_id": plan["id"], "kind": kind},
    })
    return {"mock": False, "url": session.get("url"), "id": session.get("id")}


def verify_webhook_signature(raw_body, signature_header, tolerance_seconds=300):
    """Stripe's v1 scheme: HMAC-SHA256 over "timestamp.payload"."""
    if not config.STRIPE_WEBHOOK_SECRET:
        return False, "STRIPE_WEBHOOK_SECRET is not configured."
    if not signature_header:
        return False, "Missing Stripe-Signature header."

    parts = {}
    for chunk in signature_header.split(","):
        key, _, value = chunk.strip().partition("=")
        parts.setdefault(key, []).append(value)
    timestamp = (parts.get("t") or [""])[0]
    signatures = parts.get("v1") or []
    if not timestamp or not signatures:
        return False, "Malformed Stripe-Signature header."
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False, "Malformed Stripe-Signature timestamp."
    if age > tolerance_seconds:
        return False, "Stripe signature timestamp is outside the tolerance window."

    payload = timestamp.encode() + b"." + raw_body
    expected = hmac.new(config.STRIPE_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        return False, "Stripe signature did not match."
    return True, ""


def apply_webhook_event(event):
    """Keep the local subscription in step with Stripe."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    tenant_id = metadata.get("tenant_id") or obj.get("client_reference_id")
    if not tenant_id:
        customer_id = obj.get("customer")
        if customer_id:
            row = repo.db.query_one(
                "SELECT tenant_id FROM subscriptions WHERE stripe_customer_id = ?", (customer_id,))
            tenant_id = row["tenant_id"] if row else None
    if not tenant_id or not repo.get_tenant(tenant_id):
        return "ignored: unknown tenant"

    sub = repo.get_subscription(tenant_id) or {}
    plan_id = metadata.get("plan_id") or sub.get("plan_id")
    if not plan_id:
        return "ignored: unknown plan"

    if kind == "checkout.session.completed":
        if metadata.get("kind") == "setup" or obj.get("mode") == "payment":
            repo.upsert_subscription(tenant_id, plan_id, status=sub.get("status", "trialing"),
                                     setup_paid=True,
                                     stripe_customer_id=obj.get("customer") or sub.get("stripe_customer_id", ""))
        else:
            repo.upsert_subscription(tenant_id, plan_id, status="active",
                                     stripe_customer_id=obj.get("customer") or "",
                                     stripe_subscription_id=obj.get("subscription") or "")
            repo.update_tenant(tenant_id, {"status": "active"})
    elif kind in ("customer.subscription.updated", "customer.subscription.created"):
        status_map = {"active": "active", "trialing": "trialing", "past_due": "past_due",
                      "canceled": "cancelled", "unpaid": "past_due", "incomplete": "trialing"}
        repo.upsert_subscription(
            tenant_id, plan_id, status=status_map.get(obj.get("status"), "trialing"),
            stripe_subscription_id=obj.get("id") or "",
            current_period_end=(obj.get("current_period_end") or 0) * 1000 or None)
    elif kind == "customer.subscription.deleted":
        repo.upsert_subscription(tenant_id, plan_id, status="cancelled")
        repo.update_tenant(tenant_id, {"status": "paused"})
    elif kind == "invoice.payment_failed":
        repo.upsert_subscription(tenant_id, plan_id, status="past_due")
    else:
        return f"ignored: {kind}"

    repo.log_activity(tenant_id, "billing", f"Stripe event applied: {kind}")
    return f"applied: {kind}"
