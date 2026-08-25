"""
Webhook payload normalisation and validation.

Every lead source shapes its payload differently. This module turns any of them
into the single internal lead shape and rejects anything that is not a usable
lead, so nothing unvalidated ever reaches the database or the AI prompt.
"""

from .. import security

MAX_FIELDS = 200
MAX_STRING = 500

# Aliases seen across website builders, form tools, CRMs and ad platforms.
FIELD_ALIASES = {
    "name": ("name", "full_name", "fullname", "first_name", "firstname", "contact_name",
             "your_name", "customer_name", "lead_name"),
    "last_name": ("last_name", "lastname", "surname"),
    "phone": ("phone", "phone_number", "phonenumber", "mobile", "mobile_number", "tel",
              "telephone", "cell", "contact_number", "whatsapp_number"),
    "email": ("email", "email_address", "emailaddress", "e_mail", "contact_email"),
    "service_requested": ("service", "service_requested", "service_type", "job_type",
                          "interested_in", "product", "inquiry_type", "subject"),
    "location": ("location", "address", "city", "zip", "zipcode", "postal_code", "area",
                 "street_address", "service_address"),
    "notes": ("notes", "message", "comments", "details", "description", "additional_info",
              "how_can_we_help", "body"),
    "external_id": ("id", "lead_id", "external_id", "submission_id", "entry_id"),
    "source": ("source", "utm_source", "platform", "channel", "lead_source"),
}

SOURCE_HINTS = {
    "facebook": "facebook", "fb": "facebook", "instagram": "instagram", "ig": "instagram",
    "google": "google_ads", "google_ads": "google_ads", "adwords": "google_ads",
    "gmb": "google_business", "google_business": "google_business",
    "website": "website_form", "web": "website_form", "form": "website_form",
    "phone": "phone_call", "call": "phone_call", "crm": "crm", "zapier": "webhook",
    "manual": "manual", "chat": "chat_widget",
}


ALL_ALIASES = {alias for group in FIELD_ALIASES.values() for alias in group}

LABEL_KEYS = ("name", "key", "field", "label", "column_name", "column_id", "field_name", "title")
VALUE_KEYS = ("values", "value", "answer", "string_value", "text", "content")


def _name_value_pair(item):
    """Recognise the {"name": "Email", "value": "a@b.co"} shape used by form
    builders and ad platforms, in both list and dict-of-objects form."""
    if not isinstance(item, dict):
        return None
    label = next((item.get(k) for k in LABEL_KEYS
                  if isinstance(item.get(k), str) and item.get(k)), None)
    value = next((item.get(k) for k in VALUE_KEYS if item.get(k) not in (None, "")), None)
    if isinstance(value, list):
        value = value[0] if value else ""
    if label and isinstance(value, (str, int, float, bool)):
        return str(label).strip().lower().replace(" ", "_").replace("-", "_")[:60], value
    return None


def _flatten(payload, prefix="", out=None, depth=0):
    """Flatten nested payloads to `parent_child` keys, bounded so a hostile
    deeply-nested body cannot blow up memory or recursion."""
    out = {} if out is None else out
    if depth > 4 or len(out) >= MAX_FIELDS:
        return out
    if isinstance(payload, dict):
        # Scalars first, containers second: a wide payload must never push the
        # actual contact fields past the field cap.
        items = [(str(k).strip().lower().replace(" ", "_").replace("-", "_")[:60], v)
                 for k, v in payload.items()]
        scalars = [(k, v) for k, v in items
                   if isinstance(v, (str, int, float, bool)) or v is None]
        # Known contact fields are captured first so a very wide payload cannot
        # push the phone/email past the field cap.
        for key, value in sorted(scalars, key=lambda kv: kv[0] not in ALL_ALIASES):
            if len(out) >= MAX_FIELDS:
                break
            out[f"{prefix}{key}"] = value
        for key, value in items:
            if not isinstance(value, (dict, list)):
                continue
            if len(out) >= MAX_FIELDS:
                break
            pair = _name_value_pair(value)
            if pair:
                out.setdefault(pair[0], pair[1])
                continue
            _flatten(value, f"{prefix}{key}_" if prefix else f"{key}_", out, depth + 1)
    elif isinstance(payload, list):
        # Facebook / Google style: [{"name": "email", "values": ["a@b.co"]}, ...]
        for item in payload[:MAX_FIELDS]:
            if isinstance(item, dict):
                pair = _name_value_pair(item)
                if pair:
                    out.setdefault(pair[0], pair[1])
                else:
                    _flatten(item, prefix, out, depth + 1)
    return out


def _pick(flat, keys):
    """Exact key match first, then a suffix match for prefixed/nested payloads.
    Aliases are tried in declared order so the most specific name wins."""
    for key in keys:
        if key in flat:
            cleaned = _clean(flat[key])
            if cleaned:
                return cleaned
    for key in keys:
        for flat_key, value in flat.items():
            if flat_key.endswith("_" + key) or flat_key == key:
                cleaned = _clean(value)
                if cleaned:
                    return cleaned
    return ""


def _clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ""
    if isinstance(value, bool):
        return "yes" if value else ""
    return security.clean_text(str(value), MAX_STRING)


def normalize(payload, default_source="webhook"):
    """Returns (lead_dict, error). error is None when the payload is usable."""
    if not isinstance(payload, (dict, list)):
        return None, "Payload must be a JSON object."

    # Common envelopes: {"data": {...}}, {"lead": {...}}, {"form_response": {...}}
    if isinstance(payload, dict):
        for envelope in ("data", "lead", "form_response", "entry", "payload", "fields",
                         "field_data", "answers", "user_column_data"):
            inner = payload.get(envelope)
            if isinstance(inner, (dict, list)) and inner:
                merged = _flatten(inner)
                merged.update({k: v for k, v in _flatten(
                    {k: v for k, v in payload.items() if k != envelope}).items()
                    if k not in merged})
                flat = merged
                break
        else:
            flat = _flatten(payload)
    else:
        flat = _flatten(payload)

    name = _pick(flat, FIELD_ALIASES["name"])
    last = _pick(flat, FIELD_ALIASES["last_name"])
    if last and last.lower() not in name.lower():
        name = f"{name} {last}".strip()

    phone = _pick(flat, FIELD_ALIASES["phone"])
    email = _pick(flat, FIELD_ALIASES["email"]).lower()

    if email and not security.valid_email(email):
        email = ""
    if phone and not security.valid_phone(phone):
        phone = ""

    if not (phone or email):
        return None, "A lead needs at least a valid phone number or email address."

    raw_source = _pick(flat, FIELD_ALIASES["source"]).lower()
    source = default_source
    for hint, mapped in SOURCE_HINTS.items():
        if hint in raw_source:
            source = mapped
            break

    lead = {
        "name": name[:120],
        "phone": phone[:32],
        "email": email[:254],
        "service_requested": _pick(flat, FIELD_ALIASES["service_requested"])[:120],
        "location": _pick(flat, FIELD_ALIASES["location"])[:160],
        "notes": _pick(flat, FIELD_ALIASES["notes"])[:2000],
        "external_id": _pick(flat, FIELD_ALIASES["external_id"])[:80],
        "source": source,
        "consent": True,   # submitting a lead form is the consent event
    }
    return lead, None
