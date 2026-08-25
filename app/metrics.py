"""
Reporting aggregates.

The whole product is judged on one number — APPOINTMENTS BOOKED — so that is
the headline of every summary here and everything else is supporting context.
"""

from . import db
from .db import now_ms

DAY_MS = 86400000


def _count(sql, params):
    row = db.query_one(sql, params)
    return int(row["n"]) if row and row["n"] is not None else 0


def _sum(sql, params):
    row = db.query_one(sql, params)
    return float(row["total"]) if row and row["total"] is not None else 0.0


def _range(days):
    """(since, until) in epoch ms. days=0 means all time."""
    if not days:
        return 0, now_ms() + DAY_MS
    until = now_ms() + DAY_MS
    return until - (int(days) + 1) * DAY_MS, until


def lead_counts(tenant_id, since=0, until=None):
    until = until if until is not None else now_ms() + DAY_MS
    rows = db.query(
        """SELECT status, COUNT(*) AS n FROM leads
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ? GROUP BY status""",
        (tenant_id, since, until))
    counts = {r["status"]: int(r["n"]) for r in rows}
    for status in ("NEW", "CONTACTED", "QUALIFIED", "BOOKED", "NO_RESPONSE", "LOST", "CUSTOMER"):
        counts.setdefault(status, 0)
    counts["TOTAL"] = sum(counts[s] for s in
                          ("NEW", "CONTACTED", "QUALIFIED", "BOOKED", "NO_RESPONSE", "LOST", "CUSTOMER"))
    return counts


def summary(tenant_id, days=30):
    """Powers the main dashboard."""
    since, until = _range(days)
    counts = lead_counts(tenant_id, since, until)
    total = counts["TOTAL"]

    # "Reached" = every lead the AI actually got a message out to.
    contacted = _count(
        """SELECT COUNT(*) AS n FROM leads
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ? AND last_contact_at IS NOT NULL""",
        (tenant_id, since, until))
    qualified_ever = counts["QUALIFIED"] + counts["BOOKED"] + counts["CUSTOMER"]
    booked_leads = counts["BOOKED"] + counts["CUSTOMER"]

    appointments = _count(
        """SELECT COUNT(*) AS n FROM appointments
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ? AND status <> 'cancelled'""",
        (tenant_id, since, until))
    upcoming = _count(
        """SELECT COUNT(*) AS n FROM appointments
           WHERE tenant_id = ? AND starts_at >= ? AND status = 'scheduled'""",
        (tenant_id, now_ms()))
    followups_pending = _count(
        """SELECT COUNT(*) AS n FROM leads
           WHERE tenant_id = ? AND next_followup_at IS NOT NULL AND opted_out = 0
             AND status IN ('NEW','CONTACTED','QUALIFIED')""", (tenant_id,))
    handoffs = _count(
        """SELECT COUNT(*) AS n FROM leads
           WHERE tenant_id = ? AND ai_active = 0 AND status IN ('NEW','CONTACTED','QUALIFIED')""",
        (tenant_id,))

    pipeline_value = _sum(
        """SELECT SUM(estimated_value) AS total FROM leads
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ?
             AND status IN ('QUALIFIED','BOOKED')""", (tenant_id, since, until))
    booked_value = _sum(
        """SELECT SUM(value) AS total FROM appointments
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ? AND status <> 'cancelled'""",
        (tenant_id, since, until))
    won_value = _sum(
        """SELECT SUM(estimated_value) AS total FROM leads
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ? AND status = 'CUSTOMER'""",
        (tenant_id, since, until))

    row = db.query_one(
        """SELECT AVG(first_response_ms) AS avg_ms FROM leads
           WHERE tenant_id = ? AND created_at >= ? AND first_response_ms IS NOT NULL""",
        (tenant_id, since))
    avg_response_ms = int(row["avg_ms"]) if row and row["avg_ms"] is not None else None

    return {
        "range_days": days,
        "total_leads": total,
        "new_leads": counts["NEW"],
        "contacted_leads": contacted,
        "qualified_leads": qualified_ever,
        "appointments_booked": appointments,
        "upcoming_appointments": upcoming,
        "customers_won": counts["CUSTOMER"],
        "lost_leads": counts["LOST"],
        "no_response_leads": counts["NO_RESPONSE"],
        "followups_pending": followups_pending,
        "handoffs_pending": handoffs,
        "conversion_rate": _pct(booked_leads, total),
        "response_rate": _pct(contacted, total),
        "qualification_rate": _pct(qualified_ever, total),
        "booking_rate": _pct(booked_leads, qualified_ever),
        "pipeline_value": round(pipeline_value, 2),
        "booked_value": round(booked_value, 2),
        "won_value": round(won_value, 2),
        "avg_response_seconds": round(avg_response_ms / 1000, 1) if avg_response_ms else None,
        "status_counts": counts,
    }


def _pct(part, whole):
    if not whole:
        return 0
    return round((part / whole) * 100, 1)


def timeseries(tenant_id, days=30):
    """Daily leads vs appointments, oldest first — for the reporting chart."""
    since, _ = _range(days)
    buckets = {}
    start_day = since - (since % DAY_MS)
    day = start_day
    today = now_ms() - (now_ms() % DAY_MS)
    while day <= today:
        buckets[day] = {"date": day, "leads": 0, "appointments": 0, "customers": 0}
        day += DAY_MS

    for row in db.query(
            "SELECT created_at, status FROM leads WHERE tenant_id = ? AND created_at >= ?",
            (tenant_id, start_day)):
        key = row["created_at"] - (row["created_at"] % DAY_MS)
        if key in buckets:
            buckets[key]["leads"] += 1
            if row["status"] == "CUSTOMER":
                buckets[key]["customers"] += 1
    for row in db.query(
            """SELECT created_at FROM appointments WHERE tenant_id = ? AND created_at >= ?
               AND status <> 'cancelled'""", (tenant_id, start_day)):
        key = row["created_at"] - (row["created_at"] % DAY_MS)
        if key in buckets:
            buckets[key]["appointments"] += 1
    return [buckets[k] for k in sorted(buckets)]


def source_breakdown(tenant_id, days=30):
    since, until = _range(days)
    rows = db.query(
        """SELECT source, COUNT(*) AS n,
                  SUM(CASE WHEN status IN ('BOOKED','CUSTOMER') THEN 1 ELSE 0 END) AS booked
           FROM leads WHERE tenant_id = ? AND created_at >= ? AND created_at < ?
           GROUP BY source ORDER BY n DESC""", (tenant_id, since, until))
    from .repo import SOURCE_LABELS
    out = []
    for row in rows:
        n, booked = int(row["n"]), int(row["booked"] or 0)
        out.append({"source": row["source"], "label": SOURCE_LABELS.get(row["source"], row["source"]),
                    "leads": n, "booked": booked, "booking_rate": _pct(booked, n)})
    return out


def agency_overview():
    """Powers the agency console: portfolio health at a glance."""
    from . import repo
    tenants = repo.list_tenants()
    plans = {p["id"]: p for p in repo.list_plans(active_only=False)}
    mrr_cents = 0
    setup_cents = 0
    clients = []
    for tenant in tenants:
        counts = lead_counts(tenant["id"])
        appts = _count(
            "SELECT COUNT(*) AS n FROM appointments WHERE tenant_id = ? AND status <> 'cancelled'",
            (tenant["id"],))
        sub = repo.get_subscription(tenant["id"])
        plan = plans.get(tenant.get("plan_id") or "")
        billable = tenant["status"] == "active" and not tenant["is_demo"]
        if billable and plan:
            mrr_cents += plan["monthly_cents"]
            if not (sub and sub["setup_paid"]):
                setup_cents += plan["setup_cents"]
        last_row = db.query_one(
            "SELECT MAX(created_at) AS ts FROM leads WHERE tenant_id = ?", (tenant["id"],))
        clients.append({
            "id": tenant["id"], "name": tenant["name"], "slug": tenant["slug"],
            "status": tenant["status"], "industry": tenant["industry"], "is_demo": tenant["is_demo"],
            "plan": plan["name"] if plan else None,
            "plan_slug": plan["slug"] if plan else None,
            "monthly_price": plan["monthly_price"] if plan else 0,
            "subscription_status": sub["status"] if sub else "none",
            "leads": counts["TOTAL"], "appointments": appts,
            "customers": counts["CUSTOMER"],
            "conversion_rate": _pct(counts["BOOKED"] + counts["CUSTOMER"], counts["TOTAL"]),
            "last_lead_at": last_row["ts"] if last_row else None,
            "created_at": tenant["created_at"],
        })

    real_clients = [c for c in clients if not c["is_demo"]]
    return {
        "clients_total": len(real_clients),
        "clients_active": len([c for c in real_clients if c["status"] == "active"]),
        "clients_onboarding": len([c for c in real_clients if c["status"] == "onboarding"]),
        "mrr": round(mrr_cents / 100, 2),
        "pending_setup_revenue": round(setup_cents / 100, 2),
        "annual_run_rate": round(mrr_cents * 12 / 100, 2),
        "leads_processed": sum(c["leads"] for c in clients),
        "appointments_generated": sum(c["appointments"] for c in clients),
        "clients": clients,
    }
