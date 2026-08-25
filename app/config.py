"""
Central configuration. Every credential is read from the environment — nothing
secret is ever hardcoded here or sent to the browser.

Load order: real environment variables always win over the .env file, so
hosting platforms (Fly, Render, Heroku) can override anything.
"""

import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(ROOT, "data")


def load_dotenv(path=None):
    """Minimal .env loader (stdlib only). Existing env vars are never clobbered."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            os.environ.setdefault(key.strip(), val)


load_dotenv()


def _bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# --- Server -----------------------------------------------------------------
PORT = _int("PORT", 8420)
HOST = os.environ.get("HOST", "0.0.0.0")
ENV = os.environ.get("APP_ENV", "development").lower()
IS_PRODUCTION = ENV in ("production", "prod")
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or f"http://localhost:{PORT}").rstrip("/")

DB_PATH = os.environ.get("DB_PATH") or os.path.join(DATA_DIR, "lockedinleads.db")

# --- Sessions / crypto ------------------------------------------------------
# SECRET_KEY signs session-adjacent tokens. In production it MUST be provided;
# in development we generate an ephemeral one so `python3 server.py` just works.
SECRET_KEY = os.environ.get("SECRET_KEY") or ""
if not SECRET_KEY:
    if IS_PRODUCTION:
        sys.stderr.write(
            "FATAL: SECRET_KEY must be set when APP_ENV=production.\n"
            "Generate one with:  python3 -c \"import secrets;print(secrets.token_hex(32))\"\n"
        )
        raise SystemExit(1)
    SECRET_KEY = secrets.token_hex(32)

SESSION_COOKIE = "lil_session"
SESSION_TTL_SECONDS = _int("SESSION_TTL_SECONDS", 60 * 60 * 24 * 14)
COOKIE_SECURE = _bool("COOKIE_SECURE", IS_PRODUCTION)

# --- Bootstrap agency admin -------------------------------------------------
# Used once, on first boot, to create the agency owner account.
AGENCY_NAME = os.environ.get("AGENCY_NAME", "LockedinLeads")
ADMIN_EMAIL = (os.environ.get("ADMIN_EMAIL") or "admin@lockedinleads.local").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or ""

# --- AI provider ------------------------------------------------------------
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()  # auto|anthropic|rules
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or ""
AI_MODEL = os.environ.get("AI_MODEL", "claude-opus-5")
AI_EFFORT = os.environ.get("AI_EFFORT", "low")  # low|medium|high|xhigh|max
AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 2000)
AI_TIMEOUT_SECONDS = _int("AI_TIMEOUT_SECONDS", 45)

# --- Email (SMTP) -----------------------------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST") or ""
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.environ.get("SMTP_USER") or ""
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or ""
SMTP_FROM = os.environ.get("SMTP_FROM") or SMTP_USER or "noreply@lockedinleads.local"
SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)

# --- SMS (Twilio) -----------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID") or ""
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN") or ""
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER") or ""

# --- Billing (Stripe) -------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY") or ""
# Publishable keys are designed to be public; this is the only key the browser sees.
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY") or ""
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""

# --- Automation worker ------------------------------------------------------
WORKER_ENABLED = _bool("WORKER_ENABLED", True)
WORKER_INTERVAL_SECONDS = _int("WORKER_INTERVAL_SECONDS", 20)
# Demo mode compresses follow-up delays so a live demo shows automation in seconds.
DEMO_TIME_SCALE = _int("DEMO_TIME_SCALE", 1)

SEED_DEMO = _bool("SEED_DEMO", True)

# --- Marketing site ---------------------------------------------------------
# Where the landing page's "Book a Demo" button points.
DEMO_BOOKING_URL = os.environ.get("DEMO_BOOKING_URL", "https://calendly.com/korystevens200")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")


def ai_enabled():
    """True when a live model can actually be reached."""
    if AI_PROVIDER == "rules":
        return False
    return bool(ANTHROPIC_API_KEY)


def email_configured():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def sms_configured():
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


def stripe_configured():
    return bool(STRIPE_SECRET_KEY)


def integration_status():
    """Non-secret status summary, safe to expose to authenticated admins."""
    return {
        "ai": {
            "configured": ai_enabled(),
            "provider": "anthropic" if ai_enabled() else "rules-engine",
            "model": AI_MODEL if ai_enabled() else "built-in conversation engine",
        },
        "email": {"configured": email_configured(), "provider": "smtp"},
        "sms": {"configured": sms_configured(), "provider": "twilio"},
        "billing": {"configured": stripe_configured(), "provider": "stripe"},
    }
