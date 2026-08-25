"""Sign-in, sign-out and identity."""

from .. import auth, config, repo, security
from ..http_util import HttpError, json_response
from . import router


@router.post("/api/auth/login")
def login(req):
    body = req.json
    user, token, csrf = auth.login(req, body.get("email"), body.get("password"))
    response = json_response({"user": auth.user_context(user), "csrf_token": csrf})
    return auth.attach_session_cookie(response, token)


@router.post("/api/auth/logout")
def logout(req):
    auth.logout(req)
    return auth.clear_session_cookie(json_response({"ok": True}))


@router.get("/api/auth/me")
def me(req):
    user = auth.require_user(req)
    return json_response({
        "user": auth.user_context(user, req.session),
        "csrf_token": req.session["csrf_token"],
    })


@router.post("/api/auth/password")
def change_password(req):
    user = auth.require_user(req)
    body = req.json
    current = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    if not security.verify_password(current, user["password_hash"]):
        raise HttpError(400, "Your current password is incorrect.")
    if len(new_password) < 10:
        raise HttpError(400, "Choose a password of at least 10 characters.")
    repo.set_user_password(user["id"], new_password)
    # Signing every other session out is the point of a password change.
    repo.db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?",
                    (user["id"], security.token_hash(req.session_token)))
    return json_response({"ok": True})


@router.get("/api/config")
def app_config(req):
    """Authenticated, non-secret runtime status for the app shell."""
    auth.require_user(req)
    return json_response({
        "app_name": config.AGENCY_NAME,
        "environment": config.ENV,
        "integrations": config.integration_status(),
    })
