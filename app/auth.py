"""
Authentication and authorization.

Two rules carry all of the data-isolation weight:
  1. A client user's tenant is read from their user row — never from the
     request — so no parameter can make them see another business's data.
  2. Agency admins may act on another tenant only through an explicit,
     server-recorded "acting tenant", validated to exist on every request.
"""

from . import config, repo, security
from .http_util import HttpError

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def authenticate(req):
    """Attach session/user to the request when a valid cookie is present."""
    token = req.cookie(config.SESSION_COOKIE)
    if not token:
        return None
    session = repo.get_session(token)
    if not session:
        return None
    user = repo.get_user(session["user_id"])
    if not user or user["status"] != "active":
        repo.delete_session(token)
        return None
    req.session = session
    req.session_token = token
    req.user = user
    return user


def require_user(req):
    if not req.user:
        raise HttpError(401, "Please sign in to continue.", code="unauthenticated")
    return req.user


def require_agency(req):
    user = require_user(req)
    if user["role"] != "agency_admin":
        raise HttpError(403, "Agency access required.", code="forbidden")
    return user


def verify_csrf(req):
    """Double-submit check. Cookies are SameSite=Lax, and every state-changing
    call must additionally echo the session's CSRF token in a header — which
    cross-origin pages cannot read."""
    if req.method in SAFE_METHODS or not req.session:
        return
    sent = req.header(CSRF_HEADER) or ""
    if not security.constant_time_equals(sent, req.session["csrf_token"]):
        raise HttpError(403, "Session expired or invalid. Refresh the page and try again.",
                        code="csrf_failed")


def resolve_tenant(req, requested_tenant_id=None):
    """Return the tenant id this request is permitted to operate on."""
    user = require_user(req)
    if user["role"] == "agency_admin":
        tenant_id = (requested_tenant_id or req.q("tenant_id")
                     or (req.session or {}).get("acting_tenant_id"))
        if not tenant_id:
            raise HttpError(400, "Select a client account first.", code="no_tenant_selected")
        if not repo.get_tenant(tenant_id):
            raise HttpError(404, "That client account does not exist.")
        req.tenant_id = tenant_id
        return tenant_id

    tenant_id = user["tenant_id"]
    if not tenant_id:
        raise HttpError(403, "This account is not linked to a business.", code="forbidden")
    if requested_tenant_id and requested_tenant_id != tenant_id:
        raise HttpError(403, "You do not have access to that account.", code="forbidden")
    explicit = req.q("tenant_id")
    if explicit and explicit != tenant_id:
        raise HttpError(403, "You do not have access to that account.", code="forbidden")
    req.tenant_id = tenant_id
    return tenant_id


def login(req, email, password):
    """Rate-limited by both IP and email so neither axis can be brute-forced."""
    email = (email or "").strip().lower()
    ip_key = f"login:ip:{req.remote_ip}"
    user_key = f"login:user:{email}"
    if not security.limiter.check(ip_key, 20, 300) or not security.limiter.check(user_key, 8, 300):
        raise HttpError(429, "Too many sign-in attempts. Please wait a few minutes.",
                        code="rate_limited")

    user = repo.get_user_by_email(email)
    # Always run a hash comparison so a missing account and a wrong password
    # take the same time and cannot be told apart.
    stored = user["password_hash"] if user else (
        "scrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 32)
    ok = security.verify_password(password or "", stored)
    if not user or not ok or user["status"] != "active":
        raise HttpError(401, "Email or password is incorrect.", code="invalid_credentials")

    token, csrf = repo.create_session(user["id"], req.header("User-Agent", ""))
    repo.touch_login(user["id"])
    security.limiter.reset(user_key)
    return user, token, csrf


def logout(req):
    token = getattr(req, "session_token", None) or req.cookie(config.SESSION_COOKIE)
    if token:
        repo.delete_session(token)


def user_context(user, session=None):
    """Non-secret identity payload for the frontend."""
    acting_tenant_id = (session or {}).get("acting_tenant_id") if session else None
    tenant_id = user["tenant_id"] or acting_tenant_id
    tenant = repo.get_tenant(tenant_id) if tenant_id else None
    payload = {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "is_agency": user["role"] == "agency_admin",
        "tenant": None,
        "impersonating": bool(user["role"] == "agency_admin" and acting_tenant_id),
    }
    if tenant:
        payload["tenant"] = {
            "id": tenant["id"], "name": tenant["name"], "slug": tenant["slug"],
            "industry": tenant["industry"], "status": tenant["status"],
            "timezone": tenant["timezone"], "is_demo": tenant["is_demo"],
            "onboarding_step": tenant["onboarding_step"],
            "onboarded_at": tenant["onboarded_at"],
        }
    return payload


def attach_session_cookie(response, token):
    response.set_cookie(config.SESSION_COOKIE, token, max_age=config.SESSION_TTL_SECONDS,
                        http_only=True, secure=config.COOKIE_SECURE, same_site="Lax")
    return response


def clear_session_cookie(response):
    response.set_cookie(config.SESSION_COOKIE, "", max_age=0, http_only=True,
                        secure=config.COOKIE_SECURE, same_site="Lax")
    return response
