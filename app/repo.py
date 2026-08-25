"""
Data access. Every function that touches tenant-owned data takes tenant_id as
its first argument and filters on it — that is the single mechanism enforcing
client data isolation, so nothing above this layer builds raw SQL.
"""

import json

from . import db, security, settings_schema
from .db import new_id, now_ms

LEAD_STATUSES = ("NEW", "CONTACTED", "QUALIFIED", "BOOKED", "NO_RESPONSE", "LOST", "CUSTOMER")
OPEN_STATUSES = ("NEW", "CONTACTED", "QUALIFIED")
LEAD_SOURCES = ("manual", "website_form", "facebook", "instagram", "google_ads",
                "google_business", "phone_call", "webhook", "crm", "chat_widget", "other")
SOURCE_LABELS = {
    "manual": "Manual entry", "website_form": "Website form", "facebook": "Facebook lead ad",
    "instagram": "Instagram lead ad", "google_ads": "Google Ads", "google_business": "Google Business",
    "phone_call": "Phone call", "webhook": "Webhook", "crm": "CRM", "chat_widget": "Website chat",
    "other": "Other",
}


def _json_load(raw, fallback):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


# --------------------------------------------------------------- tenants ----

def create_tenant(name, slug=None, industry="cleaning", timezone="America/New_York",
                  plan_id=None, is_demo=False, status="onboarding", **extra):
    ts = now_ms()
    slug = slug or security.slugify(name)
    base_slug, n = slug, 2
    while db.query_one("SELECT id FROM tenants WHERE slug = ?", (slug,)):
        slug = f"{base_slug}-{n}"
        n += 1
    tid = new_id("t_")
    db.execute(
        """INSERT INTO tenants (id, name, slug, industry, status, timezone, contact_name,
               contact_email, contact_phone, website, address, plan_id, is_demo,
               onboarding_step, settings_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, name, slug, industry, status, timezone, extra.get("contact_name", ""),
         extra.get("contact_email", ""), extra.get("contact_phone", ""), extra.get("website", ""),
         extra.get("address", ""), plan_id, 1 if is_demo else 0, extra.get("onboarding_step", 1),
         json.dumps(settings_schema.defaults()), ts, ts))
    return get_tenant(tid)


def get_tenant(tenant_id):
    row = db.query_one("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
    return _tenant_dict(row)


def get_tenant_by_slug(slug):
    return _tenant_dict(db.query_one("SELECT * FROM tenants WHERE slug = ?", (slug,)))


def list_tenants(include_demo=True):
    sql = "SELECT * FROM tenants"
    if not include_demo:
        sql += " WHERE is_demo = 0"
    sql += " ORDER BY is_demo ASC, created_at DESC"
    return [_tenant_dict(r) for r in db.query(sql)]


def _tenant_dict(row):
    if row is None:
        return None
    t = dict(row)
    t["settings"] = settings_schema.normalize(_json_load(t.pop("settings_json", "{}"), {}))
    t["is_demo"] = bool(t["is_demo"])
    return t


TENANT_FIELDS = ("name", "industry", "status", "timezone", "contact_name", "contact_email",
                 "contact_phone", "website", "address", "plan_id", "onboarding_step", "onboarded_at")


def update_tenant(tenant_id, patch):
    fields, values = [], []
    for key in TENANT_FIELDS:
        if key in patch:
            fields.append(f"{key} = ?")
            values.append(patch[key])
    if fields:
        values.extend([now_ms(), tenant_id])
        db.execute(f"UPDATE tenants SET {', '.join(fields)}, updated_at = ? WHERE id = ?", values)
    return get_tenant(tenant_id)


def update_tenant_settings(tenant_id, partial):
    """Merge a partial settings patch into the stored settings, re-validating."""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return None
    merged = tenant["settings"]
    for section, values in (partial or {}).items():
        if section in merged and isinstance(values, dict):
            merged[section] = {**merged[section], **values}
    normalized = settings_schema.normalize(merged)
    db.execute("UPDATE tenants SET settings_json = ?, updated_at = ? WHERE id = ?",
               (json.dumps(normalized), now_ms(), tenant_id))
    return get_tenant(tenant_id)


# ----------------------------------------------------------------- users ----

def create_user(email, password, name, role, tenant_id=None):
    email = (email or "").strip().lower()
    if not security.valid_email(email):
        raise ValueError("A valid email address is required.")
    if role not in ("agency_admin", "owner", "staff"):
        raise ValueError("Unknown role.")
    if role != "agency_admin" and not tenant_id:
        raise ValueError("Client users must belong to a business.")
    if db.query_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("An account with that email already exists.")
    uid = new_id("u_")
    db.execute(
        """INSERT INTO users (id, tenant_id, email, name, password_hash, role, status, created_at)
           VALUES (?,?,?,?,?,?,'active',?)""",
        (uid, tenant_id, email, name or "", security.hash_password(password), role, now_ms()))
    return get_user(uid)


def get_user(user_id):
    return db.row_to_dict(db.query_one("SELECT * FROM users WHERE id = ?", (user_id,)))


def get_user_by_email(email):
    return db.row_to_dict(
        db.query_one("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)))


def list_users(tenant_id):
    return db.rows_to_dicts(db.query(
        "SELECT id, tenant_id, email, name, role, status, last_login_at, created_at "
        "FROM users WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)))


def count_agency_admins():
    row = db.query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'agency_admin'")
    return row["n"] if row else 0


def set_user_password(user_id, password):
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (security.hash_password(password), user_id))


def touch_login(user_id):
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_ms(), user_id))


# -------------------------------------------------------------- sessions ----

def create_session(user_id, user_agent=""):
    token = security.random_token()
    csrf = security.random_token(24)
    ts = now_ms()
    from . import config
    db.execute(
        """INSERT INTO sessions (token_hash, user_id, csrf_token, created_at, expires_at, user_agent)
           VALUES (?,?,?,?,?,?)""",
        (security.token_hash(token), user_id, csrf, ts,
         ts + config.SESSION_TTL_SECONDS * 1000, (user_agent or "")[:200]))
    return token, csrf


def get_session(token):
    if not token:
        return None
    row = db.query_one("SELECT * FROM sessions WHERE token_hash = ?", (security.token_hash(token),))
    if row is None:
        return None
    session = dict(row)
    if session["expires_at"] < now_ms():
        delete_session(token)
        return None
    return session


def set_acting_tenant(token, tenant_id):
    db.execute("UPDATE sessions SET acting_tenant_id = ? WHERE token_hash = ?",
               (tenant_id, security.token_hash(token)))


def delete_session(token):
    db.execute("DELETE FROM sessions WHERE token_hash = ?", (security.token_hash(token),))


def purge_expired_sessions():
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_ms(),))


# ------------------------------------------------- services / areas / Qs ----

def add_service(tenant_id, name, description="", price_note="", avg_value=0,
                duration_minutes=120, sort_order=0):
    sid = new_id("s_")
    db.execute(
        """INSERT INTO services (id, tenant_id, name, description, price_note, avg_value,
               duration_minutes, active, sort_order, created_at)
           VALUES (?,?,?,?,?,?,?,1,?,?)""",
        (sid, tenant_id, name, description, price_note, float(avg_value or 0),
         int(duration_minutes or 120), sort_order, now_ms()))
    return db.row_to_dict(db.query_one("SELECT * FROM services WHERE id = ?", (sid,)))


def list_services(tenant_id, active_only=True):
    sql = "SELECT * FROM services WHERE tenant_id = ?"
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY sort_order, created_at"
    return db.rows_to_dicts(db.query(sql, (tenant_id,)))


def delete_service(tenant_id, service_id):
    db.execute("DELETE FROM services WHERE id = ? AND tenant_id = ?", (service_id, tenant_id))


def replace_services(tenant_id, items):
    with db.transaction():
        db.execute("DELETE FROM services WHERE tenant_id = ?", (tenant_id,))
        for i, item in enumerate(items or []):
            name = security.clean_text(item.get("name"), 80)
            if not name:
                continue
            db.execute(
                """INSERT INTO services (id, tenant_id, name, description, price_note, avg_value,
                       duration_minutes, active, sort_order, created_at)
                   VALUES (?,?,?,?,?,?,?,1,?,?)""",
                (new_id("s_"), tenant_id, name,
                 security.clean_text(item.get("description"), 300),
                 security.clean_text(item.get("price_note"), 120),
                 float(item.get("avg_value") or 0) if str(item.get("avg_value") or "").replace(".", "", 1).isdigit() else 0.0,
                 security.clamp_int(item.get("duration_minutes"), 15, 960, 120), i, now_ms()))
    return list_services(tenant_id)


def replace_service_areas(tenant_id, names):
    with db.transaction():
        db.execute("DELETE FROM service_areas WHERE tenant_id = ?", (tenant_id,))
        seen = set()
        for name in (names or [])[:200]:
            clean = security.clean_text(name, 80)
            if not clean or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            kind = "zip" if clean.replace("-", "").isdigit() else "city"
            db.execute("INSERT INTO service_areas (id, tenant_id, name, kind, created_at) VALUES (?,?,?,?,?)",
                       (new_id("a_"), tenant_id, clean, kind, now_ms()))
    return list_service_areas(tenant_id)


def list_service_areas(tenant_id):
    return db.rows_to_dicts(db.query(
        "SELECT * FROM service_areas WHERE tenant_id = ? ORDER BY name", (tenant_id,)))


def replace_questions(tenant_id, items):
    with db.transaction():
        db.execute("DELETE FROM questions WHERE tenant_id = ?", (tenant_id,))
        for i, item in enumerate((items or [])[:20]):
            prompt = security.clean_text(item.get("prompt"), 240)
            if not prompt:
                continue
            key = security.clean_text(item.get("field_key"), 40) or f"q{i + 1}"
            key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key.lower())
            answer_type = item.get("answer_type") if item.get("answer_type") in (
                "text", "choice", "yes_no", "date") else "text"
            options = item.get("options") or []
            if isinstance(options, str):
                options = [o.strip() for o in options.split(",") if o.strip()]
            options = [security.clean_text(o, 60) for o in options[:12] if security.clean_text(o, 60)]
            db.execute(
                """INSERT INTO questions (id, tenant_id, field_key, prompt, answer_type,
                       options_json, required, sort_order, active, created_at)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (new_id("q_"), tenant_id, key, prompt, answer_type, json.dumps(options),
                 1 if item.get("required", True) else 0, i, now_ms()))
    return list_questions(tenant_id)


def list_questions(tenant_id):
    rows = db.rows_to_dicts(db.query(
        "SELECT * FROM questions WHERE tenant_id = ? AND active = 1 ORDER BY sort_order", (tenant_id,)))
    for row in rows:
        row["options"] = _json_load(row.pop("options_json", "[]"), [])
        row["required"] = bool(row["required"])
    return rows


# ----------------------------------------------------------------- leads ----

def create_lead(tenant_id, data):
    ts = now_ms()
    lid = new_id("l_")
    source = data.get("source") if data.get("source") in LEAD_SOURCES else "manual"
    db.execute(
        """INSERT INTO leads (id, tenant_id, name, phone, email, source, service_requested,
               location, status, score, notes, estimated_value, qualification_json, ai_active,
               opted_out, consent, followup_count, external_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,0,?,?,?)""",
        (lid, tenant_id,
         security.clean_text(data.get("name"), 120),
         security.clean_text(data.get("phone"), 32),
         security.clean_text(data.get("email"), 254).lower(),
         source,
         security.clean_text(data.get("service_requested"), 120),
         security.clean_text(data.get("location"), 160),
         data.get("status") if data.get("status") in LEAD_STATUSES else "NEW",
         "unscored",
         security.clean_text(data.get("notes"), 2000),
         float(data.get("estimated_value") or 0),
         json.dumps(data.get("qualification") or {}),
         0 if data.get("ai_active") is False else 1,
         1 if data.get("consent") else 0,
         security.clean_text(data.get("external_id"), 80),
         ts, ts))
    log_activity(tenant_id, "lead_created",
                 f"New lead from {SOURCE_LABELS.get(source, source)}", lead_id=lid)
    return get_lead(tenant_id, lid)


def get_lead(tenant_id, lead_id):
    row = db.query_one("SELECT * FROM leads WHERE id = ? AND tenant_id = ?", (lead_id, tenant_id))
    return _lead_dict(row)


def find_lead_by_external_id(tenant_id, external_id):
    if not external_id:
        return None
    return _lead_dict(db.query_one(
        "SELECT * FROM leads WHERE tenant_id = ? AND external_id = ?", (tenant_id, external_id)))


def find_lead_by_contact(tenant_id, phone="", email=""):
    """De-duplicates repeat enquiries so the same person is not double-messaged."""
    phone_norm = security.normalize_phone(phone)
    email = (email or "").strip().lower()
    if phone_norm:
        for row in db.query(
                "SELECT * FROM leads WHERE tenant_id = ? AND phone <> '' ORDER BY created_at DESC LIMIT 500",
                (tenant_id,)):
            if security.normalize_phone(row["phone"]) == phone_norm:
                return _lead_dict(row)
    if email:
        row = db.query_one(
            "SELECT * FROM leads WHERE tenant_id = ? AND email = ? ORDER BY created_at DESC LIMIT 1",
            (tenant_id, email))
        if row:
            return _lead_dict(row)
    return None


def _lead_dict(row):
    if row is None:
        return None
    lead = dict(row)
    lead["qualification"] = _json_load(lead.pop("qualification_json", "{}"), {})
    lead["ai_active"] = bool(lead["ai_active"])
    lead["opted_out"] = bool(lead["opted_out"])
    lead["consent"] = bool(lead["consent"])
    lead["source_label"] = SOURCE_LABELS.get(lead["source"], lead["source"])
    return lead


def list_leads(tenant_id, status=None, search=None, source=None, limit=200, offset=0):
    sql = "SELECT * FROM leads WHERE tenant_id = ?"
    params = [tenant_id]
    if status and status in LEAD_STATUSES:
        sql += " AND status = ?"
        params.append(status)
    if source and source in LEAD_SOURCES:
        sql += " AND source = ?"
        params.append(source)
    if search:
        needle = f"%{search.strip().lower()[:60]}%"
        sql += " AND (lower(name) LIKE ? OR lower(email) LIKE ? OR phone LIKE ? OR lower(service_requested) LIKE ?)"
        params.extend([needle, needle, needle, needle])
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([security.clamp_int(limit, 1, 500, 200), security.clamp_int(offset, 0, 100000, 0)])
    return [_lead_dict(r) for r in db.query(sql, params)]


LEAD_FIELDS = ("name", "phone", "email", "source", "service_requested", "location", "status",
               "score", "notes", "estimated_value", "ai_active", "opted_out", "consent",
               "followup_count", "next_followup_at", "last_contact_at", "last_inbound_at",
               "first_response_ms", "close_reason", "external_id")


def update_lead(tenant_id, lead_id, patch):
    current = get_lead(tenant_id, lead_id)
    if not current:
        return None
    fields, values = [], []
    for key in LEAD_FIELDS:
        if key not in patch:
            continue
        value = patch[key]
        if key == "status" and value not in LEAD_STATUSES:
            continue
        if key == "source" and value not in LEAD_SOURCES:
            continue
        if key in ("ai_active", "opted_out", "consent"):
            value = 1 if value else 0
        fields.append(f"{key} = ?")
        values.append(value)
    if "qualification" in patch and isinstance(patch["qualification"], dict):
        merged = {**current["qualification"], **patch["qualification"]}
        fields.append("qualification_json = ?")
        values.append(json.dumps(merged))
    if not fields:
        return current
    values.extend([now_ms(), lead_id, tenant_id])
    db.execute(f"UPDATE leads SET {', '.join(fields)}, updated_at = ? WHERE id = ? AND tenant_id = ?",
               values)
    return get_lead(tenant_id, lead_id)


def leads_due_for_followup(now=None):
    """Worker-side query across tenants; callers re-scope by tenant when acting."""
    now = now or now_ms()
    return [_lead_dict(r) for r in db.query(
        """SELECT * FROM leads
           WHERE next_followup_at IS NOT NULL AND next_followup_at <= ?
             AND opted_out = 0 AND ai_active = 1
             AND status IN ('NEW','CONTACTED','QUALIFIED')
           ORDER BY next_followup_at LIMIT 100""", (now,))]


# -------------------------------------------------------------- messages ----

def add_message(tenant_id, lead_id, role, body, channel="chat", meta=None):
    mid = new_id("m_")
    ts = now_ms()
    db.execute(
        """INSERT INTO messages (id, tenant_id, lead_id, role, body, channel, meta_json, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (mid, tenant_id, lead_id, role, body, channel, json.dumps(meta or {}), ts))
    return {"id": mid, "tenant_id": tenant_id, "lead_id": lead_id, "role": role, "body": body,
            "channel": channel, "meta": meta or {}, "created_at": ts}


def list_messages(tenant_id, lead_id, limit=200):
    rows = db.query(
        """SELECT * FROM messages WHERE tenant_id = ? AND lead_id = ?
           ORDER BY created_at LIMIT ?""",
        (tenant_id, lead_id, security.clamp_int(limit, 1, 500, 200)))
    out = []
    for row in rows:
        item = dict(row)
        item["meta"] = _json_load(item.pop("meta_json", "{}"), {})
        out.append(item)
    return out


def count_ai_messages(tenant_id, lead_id):
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM messages WHERE tenant_id = ? AND lead_id = ? AND role = 'ai'",
        (tenant_id, lead_id))
    return row["n"] if row else 0


# ---------------------------------------------------------- appointments ----

def create_appointment(tenant_id, lead_id, starts_at, ends_at, service="", value=0, notes=""):
    aid = new_id("ap_")
    db.execute(
        """INSERT INTO appointments (id, tenant_id, lead_id, starts_at, ends_at, service,
               status, value, notes, created_at)
           VALUES (?,?,?,?,?,?,'scheduled',?,?,?)""",
        (aid, tenant_id, lead_id, int(starts_at), int(ends_at), service, float(value or 0),
         security.clean_text(notes, 500), now_ms()))
    return db.row_to_dict(db.query_one("SELECT * FROM appointments WHERE id = ?", (aid,)))


def list_appointments(tenant_id, lead_id=None, since=None, until=None, limit=200):
    sql = "SELECT * FROM appointments WHERE tenant_id = ?"
    params = [tenant_id]
    if lead_id:
        sql += " AND lead_id = ?"
        params.append(lead_id)
    if since is not None:
        sql += " AND starts_at >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND starts_at < ?"
        params.append(int(until))
    sql += " ORDER BY starts_at LIMIT ?"
    params.append(security.clamp_int(limit, 1, 500, 200))
    return db.rows_to_dicts(db.query(sql, params))


def update_appointment(tenant_id, appointment_id, patch):
    fields, values = [], []
    for key in ("starts_at", "ends_at", "status", "service", "value", "notes"):
        if key in patch:
            fields.append(f"{key} = ?")
            values.append(patch[key])
    if not fields:
        return None
    values.extend([appointment_id, tenant_id])
    db.execute(f"UPDATE appointments SET {', '.join(fields)} WHERE id = ? AND tenant_id = ?", values)
    return db.row_to_dict(db.query_one(
        "SELECT * FROM appointments WHERE id = ? AND tenant_id = ?", (appointment_id, tenant_id)))


# ------------------------------------------- activity & notifications -------

def log_activity(tenant_id, type_, message, lead_id=None, created_at=None):
    db.execute(
        "INSERT INTO activity (id, tenant_id, lead_id, type, message, created_at) VALUES (?,?,?,?,?,?)",
        (new_id("ac_"), tenant_id, lead_id, type_, message[:400], created_at or now_ms()))


def list_activity(tenant_id, limit=25):
    return db.rows_to_dicts(db.query(
        "SELECT * FROM activity WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
        (tenant_id, security.clamp_int(limit, 1, 200, 25))))


def add_notification(tenant_id, type_, title, body="", lead_id=None):
    nid = new_id("n_")
    db.execute(
        """INSERT INTO notifications (id, tenant_id, lead_id, type, title, body, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (nid, tenant_id, lead_id, type_, title[:200], body[:1000], now_ms()))
    return nid


def list_notifications(tenant_id, unread_only=False, limit=50):
    sql = "SELECT * FROM notifications WHERE tenant_id = ?"
    if unread_only:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY created_at DESC LIMIT ?"
    return db.rows_to_dicts(db.query(sql, (tenant_id, security.clamp_int(limit, 1, 200, 50))))


def mark_notifications_read(tenant_id):
    db.execute("UPDATE notifications SET read_at = ? WHERE tenant_id = ? AND read_at IS NULL",
               (now_ms(), tenant_id))


# -------------------------------------------------------------- api keys ----

def create_api_key(tenant_id, label="Default"):
    full, prefix, hashed = security.generate_api_key()
    db.execute(
        """INSERT INTO api_keys (id, tenant_id, label, key_hash, key_prefix, created_at)
           VALUES (?,?,?,?,?,?)""",
        (new_id("k_"), tenant_id, security.clean_text(label, 60) or "Default", hashed, prefix, now_ms()))
    return full


def list_api_keys(tenant_id):
    return db.rows_to_dicts(db.query(
        """SELECT id, label, key_prefix, last_used_at, revoked_at, created_at
           FROM api_keys WHERE tenant_id = ? ORDER BY created_at DESC""", (tenant_id,)))


def revoke_api_key(tenant_id, key_id):
    db.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND tenant_id = ?",
               (now_ms(), key_id, tenant_id))


def tenant_for_api_key(key):
    """Look up by hash — the plaintext key is never stored."""
    if not key or not key.startswith(security.API_KEY_PREFIX):
        return None
    row = db.query_one(
        "SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
        (security.token_hash(key),))
    if row is None:
        return None
    db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now_ms(), row["id"]))
    return get_tenant(row["tenant_id"])


# ------------------------------------------------- plans & subscriptions ----

def upsert_plan(slug, name, setup_cents, monthly_cents, features, highlight=False,
                sort_order=0, active=True, plan_id=None):
    ts = now_ms()
    existing = db.query_one("SELECT * FROM plans WHERE slug = ?", (slug,))
    if existing:
        db.execute(
            """UPDATE plans SET name=?, setup_cents=?, monthly_cents=?, features_json=?,
                   highlight=?, sort_order=?, active=?, updated_at=? WHERE slug=?""",
            (name, int(setup_cents), int(monthly_cents), json.dumps(features),
             1 if highlight else 0, sort_order, 1 if active else 0, ts, slug))
        return get_plan(existing["id"])
    pid = plan_id or new_id("pl_")
    db.execute(
        """INSERT INTO plans (id, name, slug, setup_cents, monthly_cents, features_json,
               highlight, active, sort_order, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, name, slug, int(setup_cents), int(monthly_cents), json.dumps(features),
         1 if highlight else 0, 1 if active else 0, sort_order, ts, ts))
    return get_plan(pid)


def _plan_dict(row):
    if row is None:
        return None
    plan = dict(row)
    plan["features"] = _json_load(plan.pop("features_json", "[]"), [])
    plan["highlight"] = bool(plan["highlight"])
    plan["active"] = bool(plan["active"])
    plan["setup_price"] = plan["setup_cents"] / 100
    plan["monthly_price"] = plan["monthly_cents"] / 100
    return plan


def get_plan(plan_id):
    return _plan_dict(db.query_one("SELECT * FROM plans WHERE id = ?", (plan_id,)))


def get_plan_by_slug(slug):
    return _plan_dict(db.query_one("SELECT * FROM plans WHERE slug = ?", (slug,)))


def list_plans(active_only=True):
    sql = "SELECT * FROM plans"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY sort_order, monthly_cents"
    return [_plan_dict(r) for r in db.query(sql)]


def update_plan(plan_id, patch):
    fields, values = [], []
    for key in ("name", "setup_cents", "monthly_cents", "highlight", "active", "sort_order",
                "stripe_price_id", "stripe_setup_price_id"):
        if key in patch:
            value = patch[key]
            if key in ("highlight", "active"):
                value = 1 if value else 0
            if key in ("setup_cents", "monthly_cents", "sort_order"):
                value = security.clamp_int(value, 0, 100_000_00, 0)
            fields.append(f"{key} = ?")
            values.append(value)
    if "features" in patch and isinstance(patch["features"], list):
        fields.append("features_json = ?")
        values.append(json.dumps([security.clean_text(f, 120) for f in patch["features"][:12]]))
    if not fields:
        return get_plan(plan_id)
    values.extend([now_ms(), plan_id])
    db.execute(f"UPDATE plans SET {', '.join(fields)}, updated_at = ? WHERE id = ?", values)
    return get_plan(plan_id)


def upsert_subscription(tenant_id, plan_id, status="trialing", **extra):
    ts = now_ms()
    existing = db.query_one("SELECT * FROM subscriptions WHERE tenant_id = ?", (tenant_id,))
    if existing:
        fields = ["plan_id = ?", "status = ?", "updated_at = ?"]
        values = [plan_id, status, ts]
        for key in ("setup_paid", "stripe_customer_id", "stripe_subscription_id", "current_period_end"):
            if key in extra:
                fields.append(f"{key} = ?")
                values.append(int(extra[key]) if key == "setup_paid" else extra[key])
        values.append(tenant_id)
        db.execute(f"UPDATE subscriptions SET {', '.join(fields)} WHERE tenant_id = ?", values)
    else:
        db.execute(
            """INSERT INTO subscriptions (id, tenant_id, plan_id, status, setup_paid,
                   stripe_customer_id, stripe_subscription_id, current_period_end, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (new_id("sub_"), tenant_id, plan_id, status, 1 if extra.get("setup_paid") else 0,
             extra.get("stripe_customer_id", ""), extra.get("stripe_subscription_id", ""),
             extra.get("current_period_end"), ts, ts))
    db.execute("UPDATE tenants SET plan_id = ?, updated_at = ? WHERE id = ?", (plan_id, ts, tenant_id))
    return get_subscription(tenant_id)


def get_subscription(tenant_id):
    row = db.query_one("SELECT * FROM subscriptions WHERE tenant_id = ?", (tenant_id,))
    if row is None:
        return None
    sub = dict(row)
    sub["setup_paid"] = bool(sub["setup_paid"])
    sub["plan"] = get_plan(sub["plan_id"])
    return sub


# ------------------------------------------------------------- audit logs ---

def log_webhook_event(tenant_id, source, status, reason="", lead_id=None,
                      payload_excerpt="", remote_ip=""):
    db.execute(
        """INSERT INTO webhook_events (id, tenant_id, source, status, reason, lead_id,
               payload_excerpt, remote_ip, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (new_id("we_"), tenant_id, source[:40], status, reason[:200], lead_id,
         payload_excerpt[:500], remote_ip[:64], now_ms()))


def list_webhook_events(tenant_id, limit=25):
    return db.rows_to_dicts(db.query(
        "SELECT * FROM webhook_events WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
        (tenant_id, security.clamp_int(limit, 1, 100, 25))))


def log_outbound(tenant_id, channel, recipient, subject, body, status, error="", lead_id=None):
    db.execute(
        """INSERT INTO outbound_log (id, tenant_id, lead_id, channel, recipient, subject,
               body, status, error, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (new_id("ob_"), tenant_id, lead_id, channel, recipient[:200], subject[:200],
         body[:2000], status, error[:300], now_ms()))


def list_outbound(tenant_id, limit=25):
    return db.rows_to_dicts(db.query(
        "SELECT * FROM outbound_log WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
        (tenant_id, security.clamp_int(limit, 1, 100, 25))))
