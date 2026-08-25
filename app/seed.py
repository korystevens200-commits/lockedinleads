"""
First-boot seeding: plan catalogue, the agency admin account, and a fully
populated demo business.

The demo account exists so LockedinLeads can be sold before there is a client:
it shows the complete journey — NEW → AI RESPONSE → QUALIFICATION → FOLLOW-UP
→ BOOKING → CUSTOMER — with conversations that read like real ones.
"""

import secrets

from . import config, repo, security
from .billing.plans import ensure_default_plans
from .db import now_ms

DAY = 86400000
HOUR = 3600000
MINUTE = 60000

DEMO_SLUG = "demo"
DEMO_BUSINESS = "Sparkle & Shine Cleaning Co."

DEMO_SERVICES = [
    {"name": "Standard Clean", "description": "Kitchens, bathrooms, dusting and vacuuming for regular upkeep.",
     "price_note": "From $130 for a 2-bedroom", "avg_value": 150, "duration_minutes": 120},
    {"name": "Deep Clean", "description": "Baseboards, appliances, grout — the detail work that gets skipped.",
     "price_note": "From $220 for a 3-bedroom", "avg_value": 265, "duration_minutes": 180},
    {"name": "Move In/Out Clean", "description": "Top-to-bottom clean for move day, inside cabinets and appliances.",
     "price_note": "From $320, quoted after a walkthrough", "avg_value": 340, "duration_minutes": 240},
]
DEMO_AREAS = ["Miami", "Miami Beach", "Coral Gables", "Doral", "Hialeah", "Brickell"]
DEMO_QUESTIONS = [
    {"field_key": "service_needed", "prompt": "What kind of clean are you after?",
     "answer_type": "choice", "options": ["Standard Clean", "Deep Clean", "Move In/Out Clean"],
     "required": True},
    {"field_key": "location", "prompt": "Which area is the home in?", "answer_type": "text",
     "required": True},
    {"field_key": "home_size", "prompt": "How many bedrooms and bathrooms?", "answer_type": "text",
     "required": True},
    {"field_key": "frequency", "prompt": "Is this a one-off or would you like it regularly?",
     "answer_type": "choice", "options": ["One-time", "Weekly", "Every 2 weeks", "Monthly"],
     "required": True},
]


def bootstrap():
    """Idempotent. Safe to run on every start."""
    ensure_default_plans()
    admin_password = _ensure_agency_admin()
    if config.SEED_DEMO:
        ensure_demo_tenant()
    return admin_password


def _ensure_agency_admin():
    if repo.count_agency_admins() > 0:
        return None
    password = config.ADMIN_PASSWORD or secrets.token_urlsafe(12)
    generated = not config.ADMIN_PASSWORD
    try:
        repo.create_user(config.ADMIN_EMAIL, password, config.AGENCY_NAME + " Admin", "agency_admin")
    except ValueError as exc:
        print(f"[seed] could not create the agency admin: {exc}")
        return None
    return password if generated else None


def ensure_demo_tenant():
    existing = repo.get_tenant_by_slug(DEMO_SLUG)
    if existing:
        return existing

    growth = repo.get_plan_by_slug("growth")
    tenant = repo.create_tenant(
        DEMO_BUSINESS, slug=DEMO_SLUG, industry="cleaning", timezone="America/New_York",
        plan_id=growth["id"] if growth else None, is_demo=True, status="active",
        contact_name="Maria Delgado", contact_email="owner@sparkleandshine.example",
        contact_phone="(305) 555-0100", website="https://sparkleandshine.example",
        address="1200 Brickell Ave, Miami, FL", onboarding_step=7)
    repo.update_tenant(tenant["id"], {"onboarded_at": now_ms() - 30 * DAY})
    if growth:
        repo.upsert_subscription(tenant["id"], growth["id"], status="active", setup_paid=True,
                                 current_period_end=now_ms() + 18 * DAY)

    for i, svc in enumerate(DEMO_SERVICES):
        repo.add_service(tenant["id"], sort_order=i, **svc)
    repo.replace_service_areas(tenant["id"], DEMO_AREAS)
    repo.replace_questions(tenant["id"], DEMO_QUESTIONS)
    repo.update_tenant_settings(tenant["id"], {
        "ai": {"assistant_name": "Aria", "tone": "friendly_professional"},
        "notifications": {"email_to": "owner@sparkleandshine.example", "sms_enabled": False},
    })
    repo.create_api_key(tenant["id"], "Website form")

    tenant = repo.get_tenant(tenant["id"])
    _seed_demo_leads(tenant)

    # A demo login so the account can be shown without touching a real client.
    try:
        repo.create_user("demo@lockedinleads.local", "demodemo123", "Maria Delgado (Demo)",
                         "owner", tenant["id"])
    except ValueError:
        pass
    return tenant


def _at_hour(days_from_now, hour, tenant_tz="America/New_York"):
    """A clean local time N days out — demo appointments should read like real
    slots (9:00 AM), not whatever minute the seed happened to run at."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tenant_tz)
    day = datetime.now(tz) + timedelta(days=days_from_now)
    return int(day.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp() * 1000)


def _conversation(tenant_id, lead_id, script, start_ts):
    """script: list of (role, body, minutes_offset, meta)."""
    for role, body, offset, meta in script:
        message = repo.add_message(tenant_id, lead_id, role, body,
                                   channel="sms" if role != "system" else "system", meta=meta or {})
        repo.db.execute("UPDATE messages SET created_at = ? WHERE id = ?",
                        (start_ts + offset * MINUTE, message["id"]))


def _make_lead(tenant, data, created_offset_ms, script=None, patch=None, appointment=None,
               activities=()):
    lead = repo.create_lead(tenant["id"], data)
    created = now_ms() - created_offset_ms
    repo.db.execute("UPDATE leads SET created_at = ?, updated_at = ? WHERE id = ?",
                    (created, created, lead["id"]))
    if script:
        _conversation(tenant["id"], lead["id"], script, created)
    if patch:
        repo.update_lead(tenant["id"], lead["id"], patch)
    if appointment:
        appt = repo.create_appointment(tenant["id"], lead["id"], **appointment)
        repo.db.execute("UPDATE appointments SET created_at = ? WHERE id = ?",
                        (created + 40 * MINUTE, appt["id"]))
    # create_lead() logs its own "lead_created" at the current time; drop it so the
    # demo history reads with the timestamps the script intends.
    repo.db.execute("DELETE FROM activity WHERE lead_id = ?", (lead["id"],))
    # Patching a lead stamps updated_at with "now"; roll it back to when the
    # conversation actually last moved, so the list reads like a real week.
    current = repo.get_lead(tenant["id"], lead["id"])
    last_touch = max(filter(None, [current.get("last_contact_at"),
                                   current.get("last_inbound_at"), created]))
    repo.db.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (last_touch, lead["id"]))
    for type_, message, offset in activities:
        repo.log_activity(tenant["id"], type_, message, lead["id"],
                          created_at=created + offset * MINUTE)
    return repo.get_lead(tenant["id"], lead["id"])


def _seed_demo_leads(tenant):
    tid = tenant["id"]
    day_ms = DAY

    # 1. CUSTOMER — the complete journey, finished.
    _make_lead(tenant, {
        "name": "Jenna Ortiz", "phone": "(305) 555-0142", "email": "jenna.ortiz@example.com",
        "source": "website_form", "service_requested": "Deep Clean", "location": "Coral Gables",
        "consent": True,
        "qualification": {"service_needed": "Deep Clean", "location": "Coral Gables",
                          "home_size": "3 bed / 2 bath", "frequency": "Every 2 weeks"},
    }, 9 * day_ms, script=[
        ("ai", "Hi Jenna! This is Aria from Sparkle & Shine Cleaning Co. Thanks for reaching out — "
               "what kind of clean are you after?", 0, {"pending_key": "service_needed"}),
        ("lead", "Deep clean please, the place needs it", 4, None),
        ("ai", "Perfect, Jenna! Which area is the home in?", 5, {"pending_key": "location"}),
        ("lead", "Coral Gables", 9, None),
        ("ai", "Great, we cover Coral Gables. How many bedrooms and bathrooms?", 10,
         {"pending_key": "home_size"}),
        ("lead", "3 bed 2 bath", 12, None),
        ("ai", "Got it. Is this a one-off or would you like it regularly?", 13,
         {"pending_key": "frequency"}),
        ("lead", "Every 2 weeks would be great", 16, None),
        ("ai", "Perfect, Jenna — I have everything I need. Here are the next openings:\n"
               "1. Tue at 9:00 AM\n2. Wed at 1:00 PM\n3. Thu at 9:00 AM\n\nWhich works best?", 17,
         {"offered_slots": True}),
        ("lead", "1 works", 22, None),
        ("ai", "You're booked for Tuesday at 9:00 AM. Sparkle & Shine will confirm by text before "
               "the visit — see you then!", 23, None),
        ("system", "Appointment completed — marked as customer", 3 * 24 * 60, None),
    ], patch={
        "status": "CUSTOMER", "score": "hot", "estimated_value": 265,
        "last_contact_at": now_ms() - 6 * day_ms, "last_inbound_at": now_ms() - 9 * day_ms + 22 * MINUTE,
        "first_response_ms": 38000, "consent": True,
    }, appointment={
        "starts_at": _at_hour(-6, 9), "ends_at": _at_hour(-6, 9) + 3 * HOUR,
        "service": "Deep Clean", "value": 265,
    }, activities=[("lead_created", "New lead from Website form", 0),
                   ("qualified", "Lead qualified by the assistant", 17),
                   ("booked", "Appointment booked for Tuesday 9:00 AM", 23),
                   ("customer", "Appointment completed — lead marked as customer", 4300)])
    for appt in repo.list_appointments(tid, limit=5):
        repo.update_appointment(tid, appt["id"], {"status": "completed"})

    # 2. BOOKED — booked and upcoming.
    _make_lead(tenant, {
        "name": "Marcus Lee", "phone": "(786) 555-0198", "email": "marcus.lee@example.com",
        "source": "facebook", "service_requested": "Standard Clean", "location": "Miami Beach",
        "consent": True,
        "qualification": {"service_needed": "Standard Clean", "location": "Miami Beach",
                          "home_size": "2 bed / 1 bath", "frequency": "Monthly"},
    }, 2 * day_ms, script=[
        ("ai", "Hi Marcus! Aria here from Sparkle & Shine Cleaning Co. Thanks for your enquiry — "
               "what kind of clean are you after?", 0, {"pending_key": "service_needed"}),
        ("lead", "Just a standard clean for my condo", 2, None),
        ("ai", "Got it, Marcus! Which area is the home in?", 3, {"pending_key": "location"}),
        ("lead", "Miami Beach, near Alton Rd", 6, None),
        ("ai", "We cover Miami Beach. How many bedrooms and bathrooms?", 7, {"pending_key": "home_size"}),
        ("lead", "2 bed 1 bath", 8, None),
        ("ai", "Thanks! Is this a one-off or would you like it regularly?", 9,
         {"pending_key": "frequency"}),
        ("lead", "Monthly please", 11, None),
        ("ai", "Perfect, Marcus — here are the next openings:\n1. Thu at 9:00 AM\n2. Fri at 1:00 PM\n"
               "3. Sat at 9:00 AM\n\nWhich works best?", 12, {"offered_slots": True}),
        ("lead", "Thursday morning", 25, None),
        ("ai", "You're booked for Thursday at 9:00 AM. We'll confirm by text before the visit!", 26, None),
    ], patch={
        "status": "BOOKED", "score": "hot", "estimated_value": 150,
        "last_contact_at": now_ms() - 2 * day_ms + 26 * MINUTE,
        "last_inbound_at": now_ms() - 2 * day_ms + 25 * MINUTE, "first_response_ms": 24000,
    }, appointment={
        "starts_at": _at_hour(2, 9), "ends_at": _at_hour(2, 9) + 2 * HOUR,
        "service": "Standard Clean", "value": 150,
    }, activities=[("lead_created", "New lead from Facebook lead ad", 0),
                   ("qualified", "Lead qualified by the assistant", 12),
                   ("booked", "Appointment booked for Thursday 9:00 AM", 26)])

    # 3. QUALIFIED — ready to book, waiting on a time.
    _make_lead(tenant, {
        "name": "Priya Nair", "phone": "(305) 555-0176", "email": "priya.nair@example.com",
        "source": "google_ads", "service_requested": "Move In/Out Clean", "location": "Brickell",
        "consent": True,
        "qualification": {"service_needed": "Move In/Out Clean", "location": "Brickell",
                          "home_size": "4 bed / 3 bath", "frequency": "One-time"},
    }, 5 * HOUR, script=[
        ("ai", "Hi Priya! This is Aria from Sparkle & Shine Cleaning Co. What kind of clean can we "
               "help with?", 0, {"pending_key": "service_needed"}),
        ("lead", "Move out clean, lease ends the 30th", 6, None),
        ("ai", "Got it, Priya! Which area is the home in?", 7, {"pending_key": "location"}),
        ("lead", "Brickell", 9, None),
        ("ai", "We cover Brickell. How many bedrooms and bathrooms?", 10, {"pending_key": "home_size"}),
        ("lead", "4 bed 3 bath", 14, None),
        ("ai", "Thanks! Is this a one-off or would you like it regularly?", 15,
         {"pending_key": "frequency"}),
        ("lead", "Just the one time", 18, None),
        ("ai", "Perfect, Priya — here are the next openings:\n1. Tomorrow at 9:00 AM\n"
               "2. Thu at 1:00 PM\n3. Fri at 9:00 AM\n\nWhich works best?", 19, {"offered_slots": True}),
    ], patch={
        "status": "QUALIFIED", "score": "hot", "estimated_value": 340,
        "last_contact_at": now_ms() - 5 * HOUR + 19 * MINUTE,
        "last_inbound_at": now_ms() - 5 * HOUR + 18 * MINUTE,
        "first_response_ms": 31000, "next_followup_at": now_ms() + 40 * MINUTE, "followup_count": 0,
    }, activities=[("lead_created", "New lead from Google Ads", 0),
                   ("qualified", "Lead qualified by the assistant", 19)])

    # 4. CONTACTED with follow-ups running — the automation on display.
    _make_lead(tenant, {
        "name": "Dana Whitfield", "phone": "(305) 555-0164", "email": "dana.w@example.com",
        "source": "instagram", "service_requested": "Deep Clean", "location": "",
        "consent": True, "qualification": {"service_needed": "Deep Clean"},
    }, 3 * day_ms, script=[
        ("ai", "Hi Dana! Aria here from Sparkle & Shine Cleaning Co. Thanks for reaching out about a "
               "deep clean — which area is the home in?", 0, {"pending_key": "location"}),
        ("ai", "Hi Dana — just checking in. I still have Thursday at 9:00 AM open. Want me to hold "
               "it for you?", 24 * 60, {"offered_slots": True}),
        ("ai", "Hi Dana, following up from Sparkle & Shine. Thursday at 9:00 AM is still available — "
               "should I book it?", 48 * 60, {"offered_slots": True}),
    ], patch={
        "status": "CONTACTED", "score": "warm", "estimated_value": 265, "followup_count": 2,
        "last_contact_at": now_ms() - day_ms, "first_response_ms": 19000,
        "next_followup_at": now_ms() + 6 * HOUR,
    }, activities=[("lead_created", "New lead from Instagram lead ad", 0),
                   ("followup", "Automated follow-up #1 sent", 1440),
                   ("followup", "Automated follow-up #2 sent", 2880)])

    # 5. NEW — just landed, first reply going out.
    _make_lead(tenant, {
        "name": "Tomas Rivera", "phone": "(786) 555-0111", "email": "",
        "source": "phone_call", "service_requested": "Standard Clean", "location": "Doral",
        "notes": "Missed call at 8:42am — voicemail asking about weekly cleaning.", "consent": True,
    }, 6 * MINUTE, patch={"status": "NEW", "score": "unscored"},
        activities=[("lead_created", "New lead from Phone call", 0)])

    # 6. Human takeover — a question the assistant correctly refused to answer.
    _make_lead(tenant, {
        "name": "Alicia Gomez", "phone": "(305) 555-0188", "email": "alicia.gomez@example.com",
        "source": "website_form", "service_requested": "Deep Clean", "location": "Hialeah",
        "consent": True,
        "qualification": {"service_needed": "Deep Clean", "location": "Hialeah"},
    }, 20 * HOUR, script=[
        ("ai", "Hi Alicia! Aria here from Sparkle & Shine Cleaning Co. What kind of clean can we help "
               "with?", 0, {"pending_key": "service_needed"}),
        ("lead", "Deep clean. Do you do post-construction dust removal? And can you match a $180 "
                 "quote I got?", 3, None),
        ("ai", "Great question — post-construction work and pricing matches need a quick check with "
               "the team, so I'm bringing someone in now. In the meantime, which area is the home in?",
         4, None),
        ("system", "Handed to a human: customer asked about a service and price not in the "
                   "configured list", 4, None),
        ("lead", "Hialeah", 9, None),
    ], patch={
        "status": "CONTACTED", "score": "warm", "ai_active": False, "estimated_value": 265,
        "last_contact_at": now_ms() - 20 * HOUR + 4 * MINUTE,
        "last_inbound_at": now_ms() - 20 * HOUR + 9 * MINUTE, "first_response_ms": 27000,
    }, activities=[("lead_created", "New lead from Website form", 0),
                   ("handoff", "Handed to a human: pricing question outside the configured services", 4)])
    for lead in repo.list_leads(tid, limit=50):
        if lead["name"] == "Alicia Gomez":
            repo.add_notification(tid, "handoff", "Takeover needed: Alicia Gomez",
                                  "Customer asked about post-construction cleaning and a price match.",
                                  lead["id"])

    # 7. NO_RESPONSE — the sequence ran out.
    _make_lead(tenant, {
        "name": "Kevin Barnes", "phone": "(786) 555-0155", "email": "",
        "source": "google_business", "service_requested": "", "location": "Miami", "consent": True,
    }, 12 * day_ms, script=[
        ("ai", "Hi Kevin! Aria here from Sparkle & Shine Cleaning Co. What kind of clean are you "
               "after?", 0, {"pending_key": "service_needed"}),
        ("ai", "Hi Kevin — just checking in. I still have Wednesday at 9:00 AM open.", 60, None),
        ("ai", "Hi Kevin, following up from Sparkle & Shine — should I hold a spot?", 1440, None),
        ("ai", "Hi Kevin — last check from me. Reply any time and I'll pick this straight back up.",
         4320, None),
    ], patch={
        "status": "NO_RESPONSE", "score": "cold", "followup_count": 4,
        "close_reason": "No response after all follow-ups",
        "last_contact_at": now_ms() - 9 * day_ms, "first_response_ms": 22000,
    }, activities=[("lead_created", "New lead from Google Business", 0),
                   ("no_response", "Follow-up sequence finished with no reply", 4400)])

    # 8. LOST — outside the service area.
    _make_lead(tenant, {
        "name": "Rachel Kim", "phone": "(954) 555-0133", "email": "rachel.kim@example.com",
        "source": "website_form", "service_requested": "Standard Clean", "location": "Fort Lauderdale",
        "consent": True, "qualification": {"service_needed": "Standard Clean"},
    }, 6 * day_ms, script=[
        ("ai", "Hi Rachel! Aria here from Sparkle & Shine Cleaning Co. Which area is the home in?", 0,
         {"pending_key": "location"}),
        ("lead", "Fort Lauderdale", 5, None),
        ("ai", "Thanks! That looks like it may be outside our current service area (Miami, Miami "
               "Beach, Coral Gables, Doral, Hialeah, Brickell). I'll have the team confirm and reach "
               "out if we can cover it.", 6, None),
    ], patch={
        "status": "LOST", "score": "cold", "close_reason": "Outside service area", "ai_active": False,
        "last_contact_at": now_ms() - 6 * day_ms + 6 * MINUTE, "first_response_ms": 25000,
    }, activities=[("lead_created", "New lead from Website form", 0),
                   ("out_of_area", "Lead is outside the service area", 6)])

    # 9. LOST — opted out, so messaging must stop.
    _make_lead(tenant, {
        "name": "Greg Salas", "phone": "(305) 555-0120", "email": "", "source": "facebook",
        "service_requested": "Standard Clean", "location": "Miami", "consent": True,
    }, 8 * day_ms, script=[
        ("ai", "Hi Greg! Aria here from Sparkle & Shine Cleaning Co. What kind of clean are you after?",
         0, {"pending_key": "service_needed"}),
        ("lead", "STOP", 45, None),
        ("ai", "No problem at all — I've taken you off our list. If you ever need us, Sparkle & Shine "
               "is here. Take care!", 46, None),
    ], patch={
        "status": "LOST", "score": "cold", "opted_out": True, "ai_active": False,
        "close_reason": "Opted out", "last_contact_at": now_ms() - 8 * day_ms + 46 * MINUTE,
        "first_response_ms": 21000,
    }, activities=[("lead_created", "New lead from Facebook lead ad", 0),
                   ("opt_out", "Customer opted out — messaging stopped", 46)])

    repo.add_notification(tid, "new_lead", "New lead: Tomas Rivera",
                          "Phone call · Standard Clean · Doral")
    repo.add_notification(tid, "booked", "Appointment booked: Marcus Lee",
                          "Standard Clean · Thursday 9:00 AM")
