"""
Tenant settings: defaults, deep-merge and validation.

Everything a business owner can tune without code lives here — AI behaviour,
business hours, follow-up cadence, booking availability and notifications.
Stored as a single JSON blob on the tenant row so adding a knob never needs a
migration; validated on write so the automation engine can trust it.
"""

import copy

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
              "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}

WEEKDAY_WINDOW = [{"start": "08:00", "end": "18:00"}]

DEFAULTS = {
    "ai": {
        "assistant_name": "Aria",
        "tone": "friendly_professional",     # friendly_professional|warm_casual|direct_efficient
        "custom_greeting": "",
        "extra_instructions": "",
        "auto_respond": True,
        "respond_outside_hours": True,
        "handoff_keywords": ["speak to a human", "manager", "complaint", "lawyer", "cancel my service"],
        "max_ai_messages": 25,
    },
    "hours": {
        "days": {
            "mon": copy.deepcopy(WEEKDAY_WINDOW), "tue": copy.deepcopy(WEEKDAY_WINDOW),
            "wed": copy.deepcopy(WEEKDAY_WINDOW), "thu": copy.deepcopy(WEEKDAY_WINDOW),
            "fri": copy.deepcopy(WEEKDAY_WINDOW), "sat": [{"start": "09:00", "end": "14:00"}],
            "sun": [],
        },
    },
    "followups": {
        "enabled": True,
        "delays_minutes": [15, 240, 1440, 4320],
        "max_attempts": 4,
        "only_business_hours": True,
    },
    "booking": {
        "enabled": True,
        "slot_minutes": 120,
        "buffer_minutes": 30,
        "lead_time_hours": 4,
        "max_per_day": 4,
        "days_ahead": 14,
        "availability": {
            "mon": [{"start": "09:00", "end": "16:00"}], "tue": [{"start": "09:00", "end": "16:00"}],
            "wed": [{"start": "09:00", "end": "16:00"}], "thu": [{"start": "09:00", "end": "16:00"}],
            "fri": [{"start": "09:00", "end": "16:00"}], "sat": [{"start": "09:00", "end": "13:00"}],
            "sun": [],
        },
    },
    "notifications": {
        "email_enabled": True,
        "email_to": "",
        "sms_enabled": False,
        "sms_to": "",
        "events": {"new_lead": True, "qualified": True, "booked": True, "handoff": True},
    },
}

TONES = ("friendly_professional", "warm_casual", "direct_efficient")


def defaults():
    return copy.deepcopy(DEFAULTS)


def _valid_time(value):
    try:
        hh, _, mm = str(value).partition(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def _clean_windows(raw):
    """Normalise a day's list of {start,end} windows; drop anything invalid."""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        start = _valid_time(item.get("start"))
        end = _valid_time(item.get("end"))
        if start and end and start < end:
            out.append({"start": start, "end": end})
    return out


def _clean_day_map(raw, fallback):
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for day in DAYS:
        if day in raw:
            out[day] = _clean_windows(raw.get(day))
        else:
            out[day] = copy.deepcopy(fallback.get(day, []))
    return out


def _as_bool(value, fallback):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _as_int(value, low, high, fallback):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


def _as_str(value, fallback, max_len=2000):
    if not isinstance(value, str):
        return fallback
    return value.strip()[:max_len]


def normalize(raw):
    """Merge stored/incoming settings over the defaults, coercing every field.
    Unknown keys are dropped, so a malicious payload cannot smuggle values into
    the AI prompt context."""
    raw = raw if isinstance(raw, dict) else {}
    base = defaults()

    ai_in = raw.get("ai") if isinstance(raw.get("ai"), dict) else {}
    ai = base["ai"]
    ai["assistant_name"] = _as_str(ai_in.get("assistant_name"), ai["assistant_name"], 40) or "Aria"
    tone = _as_str(ai_in.get("tone"), ai["tone"], 40)
    ai["tone"] = tone if tone in TONES else "friendly_professional"
    ai["custom_greeting"] = _as_str(ai_in.get("custom_greeting"), "", 400)
    ai["extra_instructions"] = _as_str(ai_in.get("extra_instructions"), "", 2000)
    ai["auto_respond"] = _as_bool(ai_in.get("auto_respond"), True)
    ai["respond_outside_hours"] = _as_bool(ai_in.get("respond_outside_hours"), True)
    ai["max_ai_messages"] = _as_int(ai_in.get("max_ai_messages"), 3, 100, 25)
    kw = ai_in.get("handoff_keywords")
    if isinstance(kw, list):
        ai["handoff_keywords"] = [_as_str(k, "", 60).lower() for k in kw[:20] if _as_str(k, "", 60)]
    elif isinstance(kw, str):
        ai["handoff_keywords"] = [p.strip().lower() for p in kw.split(",") if p.strip()][:20]

    hours_in = raw.get("hours") if isinstance(raw.get("hours"), dict) else {}
    base["hours"]["days"] = _clean_day_map(hours_in.get("days"), DEFAULTS["hours"]["days"])

    fu_in = raw.get("followups") if isinstance(raw.get("followups"), dict) else {}
    fu = base["followups"]
    fu["enabled"] = _as_bool(fu_in.get("enabled"), True)
    fu["only_business_hours"] = _as_bool(fu_in.get("only_business_hours"), True)
    delays = fu_in.get("delays_minutes")
    if isinstance(delays, str):
        delays = [d.strip() for d in delays.split(",") if d.strip()]
    if isinstance(delays, list) and delays:
        cleaned = []
        for d in delays[:10]:
            n = _as_int(d, 1, 60 * 24 * 30, None)
            if n:
                cleaned.append(n)
        if cleaned:
            fu["delays_minutes"] = sorted(cleaned)
    fu["max_attempts"] = _as_int(fu_in.get("max_attempts"), 0, 10, len(fu["delays_minutes"]))

    bk_in = raw.get("booking") if isinstance(raw.get("booking"), dict) else {}
    bk = base["booking"]
    bk["enabled"] = _as_bool(bk_in.get("enabled"), True)
    bk["slot_minutes"] = _as_int(bk_in.get("slot_minutes"), 15, 480, 120)
    bk["buffer_minutes"] = _as_int(bk_in.get("buffer_minutes"), 0, 240, 30)
    bk["lead_time_hours"] = _as_int(bk_in.get("lead_time_hours"), 0, 168, 4)
    bk["max_per_day"] = _as_int(bk_in.get("max_per_day"), 1, 50, 4)
    bk["days_ahead"] = _as_int(bk_in.get("days_ahead"), 1, 90, 14)
    bk["availability"] = _clean_day_map(bk_in.get("availability"), DEFAULTS["booking"]["availability"])

    nt_in = raw.get("notifications") if isinstance(raw.get("notifications"), dict) else {}
    nt = base["notifications"]
    nt["email_enabled"] = _as_bool(nt_in.get("email_enabled"), True)
    nt["sms_enabled"] = _as_bool(nt_in.get("sms_enabled"), False)
    nt["email_to"] = _as_str(nt_in.get("email_to"), "", 254)
    nt["sms_to"] = _as_str(nt_in.get("sms_to"), "", 32)
    ev_in = nt_in.get("events") if isinstance(nt_in.get("events"), dict) else {}
    for key in list(nt["events"].keys()):
        nt["events"][key] = _as_bool(ev_in.get(key), nt["events"][key])

    return base
