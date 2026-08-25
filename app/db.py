"""
SQLite storage layer.

Chosen over the previous JSON file because the product is now multi-tenant:
every query is scoped by tenant_id, which a shared JSON blob cannot enforce.
sqlite3 ships with Python, so this adds no dependency.

Connections are per-thread (the HTTP server and the automation worker run in
different threads) and WAL mode lets readers and the writer work concurrently.
"""

import os
import sqlite3
import threading
import time
import uuid

from . import config

_local = threading.local()
_init_lock = threading.Lock()
_initialised = False

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tenants (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    industry        TEXT NOT NULL DEFAULT 'cleaning',
    status          TEXT NOT NULL DEFAULT 'onboarding',   -- onboarding|active|paused|cancelled
    timezone        TEXT NOT NULL DEFAULT 'America/New_York',
    contact_name    TEXT DEFAULT '',
    contact_email   TEXT DEFAULT '',
    contact_phone   TEXT DEFAULT '',
    website         TEXT DEFAULT '',
    address         TEXT DEFAULT '',
    plan_id         TEXT,
    is_demo         INTEGER NOT NULL DEFAULT 0,
    onboarding_step INTEGER NOT NULL DEFAULT 1,
    onboarded_at    INTEGER,
    settings_json   TEXT NOT NULL DEFAULT '{}',
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT,                    -- NULL for agency staff
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,           -- agency_admin|owner|staff
    status        TEXT NOT NULL DEFAULT 'active',
    last_login_at INTEGER,
    created_at    INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    -- Agency admins can "view as" a client; the impersonated tenant lives here
    -- rather than in a client-supplied header so it cannot be forged.
    acting_tenant_id TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    user_agent TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS services (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    price_note  TEXT DEFAULT '',          -- free text; AI quotes only what is written here
    avg_value   REAL NOT NULL DEFAULT 0,  -- used for pipeline value estimates
    duration_minutes INTEGER NOT NULL DEFAULT 120,
    active      INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_services_tenant ON services(tenant_id);

CREATE TABLE IF NOT EXISTS service_areas (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'city',   -- city|zip|region
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_areas_tenant ON service_areas(tenant_id);

CREATE TABLE IF NOT EXISTS questions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    field_key   TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    answer_type TEXT NOT NULL DEFAULT 'text',   -- text|choice|yes_no|date
    options_json TEXT NOT NULL DEFAULT '[]',
    required    INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_questions_tenant ON questions(tenant_id);

CREATE TABLE IF NOT EXISTS leads (
    id             TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    name           TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    email          TEXT DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'manual',
    service_requested TEXT DEFAULT '',
    location       TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'NEW',
    score          TEXT NOT NULL DEFAULT 'unscored',   -- hot|warm|cold|unscored
    notes          TEXT DEFAULT '',
    estimated_value REAL NOT NULL DEFAULT 0,
    qualification_json TEXT NOT NULL DEFAULT '{}',
    ai_active      INTEGER NOT NULL DEFAULT 1,
    opted_out      INTEGER NOT NULL DEFAULT 0,
    consent        INTEGER NOT NULL DEFAULT 0,
    followup_count INTEGER NOT NULL DEFAULT 0,
    next_followup_at INTEGER,
    last_contact_at  INTEGER,
    last_inbound_at  INTEGER,
    first_response_ms INTEGER,          -- speed-to-lead, the metric that sells this
    close_reason   TEXT DEFAULT '',
    external_id    TEXT DEFAULT '',
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_followup ON leads(next_followup_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_external ON leads(tenant_id, external_id)
    WHERE external_id <> '';

CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    lead_id    TEXT NOT NULL,
    role       TEXT NOT NULL,          -- lead|ai|human|system
    body       TEXT NOT NULL,
    channel    TEXT NOT NULL DEFAULT 'chat',   -- chat|sms|email|system
    meta_json  TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages(lead_id, created_at);

CREATE TABLE IF NOT EXISTS appointments (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    lead_id    TEXT NOT NULL,
    starts_at  INTEGER NOT NULL,
    ends_at    INTEGER NOT NULL,
    service    TEXT DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'scheduled',   -- scheduled|completed|cancelled|no_show
    value      REAL NOT NULL DEFAULT 0,
    notes      TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_appts_tenant ON appointments(tenant_id, starts_at);

CREATE TABLE IF NOT EXISTS activity (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    lead_id    TEXT,
    type       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_tenant ON activity(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    lead_id    TEXT,
    type       TEXT NOT NULL,       -- new_lead|qualified|booked|handoff
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    read_at    INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_tenant ON notifications(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT 'Default',
    key_hash    TEXT NOT NULL,
    key_prefix  TEXT NOT NULL,
    last_used_at INTEGER,
    revoked_at  INTEGER,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_apikeys_hash ON api_keys(key_hash);

CREATE TABLE IF NOT EXISTS plans (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    setup_cents   INTEGER NOT NULL DEFAULT 0,
    monthly_cents INTEGER NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'usd',
    features_json TEXT NOT NULL DEFAULT '[]',
    highlight     INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    stripe_price_id       TEXT DEFAULT '',
    stripe_setup_price_id TEXT DEFAULT '',
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL UNIQUE,
    plan_id    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'trialing',  -- trialing|active|past_due|cancelled
    setup_paid INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id     TEXT DEFAULT '',
    stripe_subscription_id TEXT DEFAULT '',
    current_period_end     INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    source     TEXT NOT NULL DEFAULT 'unknown',
    status     TEXT NOT NULL,        -- accepted|rejected
    reason     TEXT DEFAULT '',
    lead_id    TEXT,
    payload_excerpt TEXT DEFAULT '',
    remote_ip  TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_webhook_tenant ON webhook_events(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS outbound_log (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    lead_id    TEXT,
    channel    TEXT NOT NULL,        -- email|sms
    recipient  TEXT NOT NULL DEFAULT '',
    subject    TEXT DEFAULT '',
    body       TEXT DEFAULT '',
    status     TEXT NOT NULL,        -- sent|simulated|failed
    error      TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbound_tenant ON outbound_log(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_ms():
    return int(time.time() * 1000)


def new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:20]}"


def connect():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        _local.conn = conn
    return conn


def close_thread_connection():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init():
    global _initialised
    with _init_lock:
        if _initialised:
            return
        conn = connect()
        conn.executescript(SCHEMA)
        _initialised = True


def query(sql, params=()):
    return connect().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return connect().execute(sql, params).fetchone()


def execute(sql, params=()):
    return connect().execute(sql, params)


class transaction:
    """Context manager wrapping a write batch in a single BEGIN/COMMIT."""

    def __enter__(self):
        self.conn = connect()
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_dicts(rows):
    return [dict(r) for r in rows]
