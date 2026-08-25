"""
Password hashing, token generation, rate limiting and input validation.

Password hashing uses hashlib.scrypt (stdlib, memory-hard). Session tokens are
stored hashed so a database leak cannot be replayed as a live session.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                        r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
    except Exception:
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def random_token(nbytes=32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """SHA-256 is the right primitive here: the input is already high-entropy."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


# --- API keys ---------------------------------------------------------------

API_KEY_PREFIX = "lil_live_"


def generate_api_key():
    """Returns (full_key, prefix, hash). The full key is shown to the user once."""
    raw = secrets.token_urlsafe(32)
    full = API_KEY_PREFIX + raw
    return full, full[:16], token_hash(full)


# --- Rate limiting ----------------------------------------------------------

class RateLimiter:
    """In-memory sliding window. Adequate for a single-process deployment; swap
    for Redis if this ever runs multi-process."""

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def check(self, key, limit, window_seconds):
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if t > cutoff]
            allowed = len(bucket) < limit
            if allowed:
                bucket.append(now)
            self._hits[key] = bucket
            if len(self._hits) > 5000:  # crude cleanup so this cannot grow forever
                for k in [k for k, v in self._hits.items() if not v or max(v) < cutoff]:
                    self._hits.pop(k, None)
        return allowed

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


limiter = RateLimiter()


# --- Validation -------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
PHONE_ALLOWED_RE = re.compile(r"^[+0-9\s().\-]{7,32}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")


def valid_email(value) -> bool:
    return bool(value and isinstance(value, str) and len(value) <= 254 and EMAIL_RE.match(value.strip()))


def normalize_phone(value):
    """Reduce a human-typed number to +digits so duplicates match and SMS works."""
    if not value or not isinstance(value, str):
        return ""
    keep = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if keep.startswith("+"):
        return "+" + "".join(ch for ch in keep[1:] if ch.isdigit())
    return "".join(ch for ch in keep if ch.isdigit())


def valid_phone(value) -> bool:
    if not value or not isinstance(value, str) or not PHONE_ALLOWED_RE.match(value.strip()):
        return False
    digits = "".join(ch for ch in value if ch.isdigit())
    return 7 <= len(digits) <= 15


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return (slug or "client")[:48]


def clean_text(value, max_len=500, default=""):
    """Trim, cap length, and strip control characters. Output is always escaped
    at render time as well — this is a data-hygiene layer, not the XSS defence."""
    if value is None:
        return default
    if not isinstance(value, str):
        value = str(value)
    value = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return value.strip()[:max_len]


def clamp_int(value, low, high, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))


# --- Signed values ----------------------------------------------------------

def sign_value(value: str, secret: str) -> str:
    """Opaque, tamper-evident handle for anonymous chat sessions: a website
    visitor can continue their own conversation without an account, and cannot
    guess or edit their way into anyone else's."""
    mac = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{value}.{mac}"


def unsign_value(token: str, secret: str):
    if not token or "." not in token:
        return None
    value, _, mac = token.rpartition(".")
    expected = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return value if hmac.compare_digest(expected, mac) else None
