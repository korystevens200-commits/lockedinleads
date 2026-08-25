"""
Business hours and appointment availability.

Everything here is timezone-aware against the tenant's own timezone — a
cleaning company in Miami and one in Phoenix must not share a clock. The AI is
only ever handed slots this module produced, which is what stops it inventing
availability.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import repo
from ..db import now_ms
from ..settings_schema import DAYS

MINUTE_MS = 60000
HOUR_MS = 3600000
DAY_MS = 86400000


def tz_for(tenant):
    try:
        return ZoneInfo(tenant.get("timezone") or "America/New_York")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def to_local(ts_ms, tenant):
    return datetime.fromtimestamp(ts_ms / 1000, tz=tz_for(tenant))


def to_ms(dt):
    return int(dt.timestamp() * 1000)


def _parse_hhmm(value):
    hh, _, mm = value.partition(":")
    return int(hh), int(mm)


def _windows_for(day_map, dt):
    return day_map.get(DAYS[dt.weekday()], [])


def is_within_business_hours(tenant, ts_ms=None):
    ts_ms = ts_ms if ts_ms is not None else now_ms()
    local = to_local(ts_ms, tenant)
    windows = _windows_for(tenant["settings"]["hours"]["days"], local)
    current = local.strftime("%H:%M")
    return any(w["start"] <= current < w["end"] for w in windows)


def next_business_open(tenant, ts_ms=None):
    """First moment at or after ts_ms that falls inside business hours."""
    ts_ms = ts_ms if ts_ms is not None else now_ms()
    local = to_local(ts_ms, tenant)
    day_map = tenant["settings"]["hours"]["days"]
    for offset in range(0, 14):
        day = (local + timedelta(days=offset)).replace(second=0, microsecond=0)
        for window in _windows_for(day_map, day):
            sh, sm = _parse_hhmm(window["start"])
            eh, em = _parse_hhmm(window["end"])
            start = day.replace(hour=sh, minute=sm)
            end = day.replace(hour=eh, minute=em)
            if offset == 0 and local >= end:
                continue
            candidate = max(start, local) if offset == 0 else start
            if candidate < end:
                return to_ms(candidate)
    return ts_ms  # no hours configured at all — do not stall the pipeline


def format_slot(ts_ms, tenant, include_year=False):
    local = to_local(ts_ms, tenant)
    fmt = "%a %b %-d" + (" %Y" if include_year else "") + " at %-I:%M %p"
    try:
        return local.strftime(fmt)
    except ValueError:                      # platforms without %-d support
        return local.strftime("%a %b %d at %I:%M %p").replace(" 0", " ")


def open_slots(tenant, count=3, from_ms=None, service=None):
    """Real open appointment slots, honouring availability windows, lead time,
    slot length + buffer, per-day caps and already-booked appointments."""
    booking = tenant["settings"]["booking"]
    if not booking.get("enabled", True):
        return []

    now = from_ms or now_ms()
    earliest = now + booking["lead_time_hours"] * HOUR_MS
    slot_ms = booking["slot_minutes"] * MINUTE_MS
    if service and service.get("duration_minutes"):
        slot_ms = max(slot_ms, int(service["duration_minutes"]) * MINUTE_MS)
    step_ms = slot_ms + booking["buffer_minutes"] * MINUTE_MS

    horizon_end = now + booking["days_ahead"] * DAY_MS
    booked = repo.list_appointments(tenant["id"], since=now - DAY_MS, until=horizon_end, limit=500)
    busy = [(a["starts_at"], a["ends_at"]) for a in booked if a["status"] != "cancelled"]
    per_day = {}
    for start, _ in busy:
        key = to_local(start, tenant).date().isoformat()
        per_day[key] = per_day.get(key, 0) + 1

    tz = tz_for(tenant)
    availability = booking["availability"]
    slots = []
    day0 = datetime.fromtimestamp(now / 1000, tz=tz).replace(hour=0, minute=0, second=0, microsecond=0)

    for offset in range(0, booking["days_ahead"] + 1):
        if len(slots) >= count:
            break
        day = day0 + timedelta(days=offset)
        day_key = day.date().isoformat()
        if per_day.get(day_key, 0) >= booking["max_per_day"]:
            continue
        for window in _windows_for(availability, day):
            sh, sm = _parse_hhmm(window["start"])
            eh, em = _parse_hhmm(window["end"])
            cursor = day.replace(hour=sh, minute=sm)
            window_end = day.replace(hour=eh, minute=em)
            while to_ms(cursor) + slot_ms <= to_ms(window_end):
                start_ms = to_ms(cursor)
                end_ms = start_ms + slot_ms
                if start_ms < earliest:
                    cursor += timedelta(milliseconds=step_ms)
                    continue
                overlap = any(start_ms < b_end and end_ms > b_start for b_start, b_end in busy)
                if not overlap and per_day.get(day_key, 0) < booking["max_per_day"]:
                    slots.append({
                        "starts_at": start_ms,
                        "ends_at": end_ms,
                        "label": format_slot(start_ms, tenant),
                    })
                    per_day[day_key] = per_day.get(day_key, 0) + 1
                    if len(slots) >= count:
                        break
                    # one offer per day keeps the choices feeling like real options
                    break
                cursor += timedelta(milliseconds=step_ms)
            if len(slots) >= count:
                break
    return slots


def slot_is_available(tenant, starts_at, ends_at):
    """Re-checked at booking time so two leads cannot claim the same slot."""
    overlapping = repo.list_appointments(tenant["id"], since=starts_at - DAY_MS,
                                         until=ends_at + DAY_MS, limit=500)
    for appt in overlapping:
        if appt["status"] == "cancelled":
            continue
        if starts_at < appt["ends_at"] and ends_at > appt["starts_at"]:
            return False
    return True


def humanize_hours(tenant):
    """Compact business-hours summary for the AI prompt and the UI."""
    day_map = tenant["settings"]["hours"]["days"]
    labels = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
              "fri": "Fri", "sat": "Sat", "sun": "Sun"}
    parts = []
    for day in DAYS:
        windows = day_map.get(day, [])
        if not windows:
            parts.append(f"{labels[day]}: closed")
        else:
            parts.append(f"{labels[day]}: " + ", ".join(f"{w['start']}-{w['end']}" for w in windows))
    return "; ".join(parts)
