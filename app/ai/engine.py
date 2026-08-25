"""
Conversation engine — the core of the product.

Owns the whole lead lifecycle: instant response, qualification, follow-up
scheduling, booking, opt-outs and human handoff. Routes/webhooks/worker all
call into here so the behaviour is identical no matter where a lead came from.
"""

from .. import repo
from ..automation import schedule
from ..db import now_ms
from ..notifications import (deliver_to_lead, notify_appointment_booked, notify_handoff,
                             notify_new_lead, notify_qualified)
from . import prompt
from .provider import get_provider
from .rules_provider import RulesProvider

MINUTE_MS = 60000

TERMINAL_STATUSES = ("BOOKED", "LOST", "CUSTOMER", "NO_RESPONSE")


def _provider():
    return get_provider()


def _generate(ctx, directive, incoming=None):
    """Run the configured provider, falling back to the rules engine on failure
    so a lead is never left unanswered because of an API problem."""
    provider = _provider()
    turn = provider.generate(ctx, directive=directive, incoming=incoming)
    if (not turn.reply and directive != "reply") or turn.error or (
            not turn.reply and turn.intent not in ("booking_selected", "opt_out")):
        if turn.error:
            print(f"[ai] {provider.name} unavailable ({turn.error}) — using built-in engine")
        fallback = RulesProvider().generate(ctx, directive=directive, incoming=incoming)
        fallback.provider = f"{provider.name}->rules" if turn.error else fallback.provider
        if turn.intent == "booking_selected":
            return turn
        return fallback
    return turn


def _schedule_next_followup(tenant, lead_id, attempt):
    """Next nudge time from the tenant's cadence, pushed into business hours if
    the tenant asked for that. Returns None once the cadence is exhausted."""
    cfg = tenant["settings"]["followups"]
    if not cfg.get("enabled", True):
        return None
    delays = cfg["delays_minutes"]
    max_attempts = min(cfg.get("max_attempts", len(delays)), len(delays))
    if attempt >= max_attempts:
        return None
    when = now_ms() + delays[attempt] * MINUTE_MS
    if cfg.get("only_business_hours", True):
        when = max(when, schedule.next_business_open(tenant, when))
    return when


def _apply_contact_updates(tenant_id, lead, turn):
    """Only ever fills blanks — the AI must not overwrite verified contact data."""
    patch = {}
    if turn.lead_name and not lead.get("name"):
        patch["name"] = turn.lead_name
    if turn.lead_email and not lead.get("email"):
        patch["email"] = turn.lead_email.lower()
    if turn.lead_phone and not lead.get("phone"):
        patch["phone"] = turn.lead_phone
    if turn.service_interest and not lead.get("service_requested"):
        patch["service_requested"] = turn.service_interest
    if turn.location and not lead.get("location"):
        patch["location"] = turn.location
    if turn.qualification_updates:
        patch["qualification"] = turn.qualification_updates
    if turn.score and turn.score != "unscored":
        patch["score"] = turn.score
    if patch:
        return repo.update_lead(tenant_id, lead["id"], patch)
    return lead


def _estimated_value(tenant, lead):
    """Pipeline value from the tenant's own average service value — never invented."""
    if lead.get("estimated_value"):
        return float(lead["estimated_value"])
    services = repo.list_services(tenant["id"])
    wanted = (lead.get("service_requested") or "").lower()
    for svc in services:
        if svc["name"].lower() in wanted or wanted in svc["name"].lower():
            return float(svc["avg_value"] or 0)
    values = [float(s["avg_value"] or 0) for s in services if s["avg_value"]]
    return round(sum(values) / len(values), 2) if values else 0.0


def _record_ai_message(tenant, lead, turn, channel_hint=None):
    channel = channel_hint or deliver_to_lead(tenant, lead, turn.reply)
    return repo.add_message(
        tenant["id"], lead["id"], "ai", turn.reply, channel=channel,
        meta={"pending_key": turn.pending_key, "offered_slots": turn.offered_slots,
              "provider": turn.provider, "intent": turn.intent})


def _offered_slots(turn, slots):
    """The Anthropic provider doesn't flag this explicitly, so infer it from the
    reply when times were on the table."""
    if turn.offered_slots:
        return True
    if not slots or not turn.reply:
        return False
    low = turn.reply.lower()
    return any(slot["label"].split(" at ")[0].lower() in low for slot in slots)


# ------------------------------------------------------------------ flows ---

def handle_new_lead(tenant, lead, force=False):
    """Instant response the moment a lead lands. Returns the messages created."""
    notify_new_lead(tenant, lead)
    ai_cfg = tenant["settings"]["ai"]

    if not force and (not ai_cfg.get("auto_respond", True) or not lead.get("ai_active")):
        repo.update_lead(tenant["id"], lead["id"], {"next_followup_at": None})
        return []

    if not ai_cfg.get("respond_outside_hours", True) and not schedule.is_within_business_hours(tenant):
        # Hold the first message until the business opens, and say so in the log.
        repo.update_lead(tenant["id"], lead["id"],
                         {"next_followup_at": schedule.next_business_open(tenant)})
        repo.log_activity(tenant["id"], "queued",
                          "Outside business hours — first reply queued for opening time", lead["id"])
        return []

    slots = schedule.open_slots(tenant, count=3)
    ctx = prompt.build_context(tenant, lead, [], slots=slots)
    turn = _generate(ctx, "opening")
    if not turn.reply:
        return []

    lead = _apply_contact_updates(tenant["id"], lead, turn)
    turn.offered_slots = _offered_slots(turn, slots)
    message = _record_ai_message(tenant, lead, turn)

    created = lead["created_at"]
    repo.update_lead(tenant["id"], lead["id"], {
        "status": "CONTACTED" if lead["status"] == "NEW" else lead["status"],
        "last_contact_at": now_ms(),
        "first_response_ms": max(0, now_ms() - created),
        "next_followup_at": _schedule_next_followup(tenant, lead["id"], 0),
        "estimated_value": _estimated_value(tenant, lead),
    })
    repo.log_activity(tenant["id"], "ai_reply", "Assistant sent the first response", lead["id"])
    return [message]


def handle_inbound(tenant, lead, text, channel="chat"):
    """A message from the lead. Stores it, then replies unless a human took over."""
    text = (text or "").strip()[:2000]
    if not text:
        return []

    inbound = repo.add_message(tenant["id"], lead["id"], "lead", text, channel=channel)
    lead = repo.update_lead(tenant["id"], lead["id"], {
        "last_inbound_at": now_ms(),
        "next_followup_at": None,          # a reply always cancels the follow-up chain
        "followup_count": 0,
        "status": "CONTACTED" if lead["status"] in ("NEW", "NO_RESPONSE") else lead["status"],
    })

    if not lead["ai_active"]:
        repo.log_activity(tenant["id"], "inbound",
                          "Customer replied (human takeover is on — assistant did not respond)",
                          lead["id"])
        repo.add_notification(tenant["id"], "handoff", f"Reply from {lead.get('name') or 'lead'}",
                              text[:200], lead["id"])
        return [inbound]

    if repo.count_ai_messages(tenant["id"], lead["id"]) >= tenant["settings"]["ai"]["max_ai_messages"]:
        return [inbound] + _handoff(tenant, lead, "conversation length limit reached")

    slots = schedule.open_slots(tenant, count=3)
    history = repo.list_messages(tenant["id"], lead["id"])
    # The inbound message is already stored; pass history up to it and the text
    # separately so providers see a clean "latest user turn".
    ctx = prompt.build_context(tenant, lead, history[:-1], slots=slots)
    turn = _generate(ctx, "reply", incoming=text)
    lead = _apply_contact_updates(tenant["id"], lead, turn)

    if turn.intent == "opt_out":
        return [inbound] + _opt_out(tenant, lead, turn)
    if turn.needs_human or turn.intent == "needs_human":
        return [inbound] + _handoff(tenant, lead, "customer asked for a person", turn)
    if turn.intent == "booking_selected" and 0 <= turn.selected_slot_index < len(slots):
        return [inbound] + _book(tenant, lead, slots[turn.selected_slot_index], turn)
    if turn.intent == "not_interested":
        return [inbound] + _closed_lost(tenant, lead, turn)
    if turn.intent == "out_of_area":
        return [inbound] + _out_of_area(tenant, lead, turn)

    if not turn.reply:
        return [inbound]

    turn.offered_slots = _offered_slots(turn, slots)
    message = _record_ai_message(tenant, lead, turn)

    was_qualified = lead["status"] in ("QUALIFIED", "BOOKED", "CUSTOMER")
    status = lead["status"]
    if turn.qualified and status in ("NEW", "CONTACTED"):
        status = "QUALIFIED"
    patch = {
        "status": status,
        "last_contact_at": now_ms(),
        "next_followup_at": _schedule_next_followup(tenant, lead["id"], 0),
        "estimated_value": _estimated_value(tenant, lead),
    }
    if lead.get("first_response_ms") is None:
        patch["first_response_ms"] = max(0, now_ms() - lead["created_at"])
    lead = repo.update_lead(tenant["id"], lead["id"], patch)

    if status == "QUALIFIED" and not was_qualified:
        repo.log_activity(tenant["id"], "qualified", "Lead qualified by the assistant", lead["id"])
        notify_qualified(tenant, lead)
    if turn.unanswered_question:
        repo.log_activity(tenant["id"], "needs_answer",
                          f"Customer asked something the assistant could not answer: {turn.unanswered_question}",
                          lead["id"])
        repo.add_notification(tenant["id"], "handoff", "Customer asked a question the assistant deferred",
                              turn.unanswered_question, lead["id"])
    return [inbound, message]


def run_followup(tenant, lead):
    """One scheduled nudge. Returns the messages created (possibly none)."""
    cfg = tenant["settings"]["followups"]
    if (lead["opted_out"] or not lead["ai_active"] or lead["status"] in TERMINAL_STATUSES
            or not cfg.get("enabled", True)):
        repo.update_lead(tenant["id"], lead["id"], {"next_followup_at": None})
        return []

    attempt = int(lead["followup_count"] or 0)
    max_attempts = min(cfg.get("max_attempts", len(cfg["delays_minutes"])), len(cfg["delays_minutes"]))
    if attempt >= max_attempts:
        return _exhausted(tenant, lead)

    # A lead that has never been contacted gets the opening message instead —
    # this is the path for messages queued outside business hours.
    if lead.get("last_contact_at") is None:
        return handle_new_lead(tenant, lead, force=True)

    slots = schedule.open_slots(tenant, count=3)
    history = repo.list_messages(tenant["id"], lead["id"])
    ctx = prompt.build_context(tenant, lead, history, slots=slots)
    turn = _generate(ctx, "followup")
    if not turn.reply:
        return []

    turn.offered_slots = _offered_slots(turn, slots)
    message = _record_ai_message(tenant, lead, turn)
    next_at = _schedule_next_followup(tenant, lead["id"], attempt + 1)
    repo.update_lead(tenant["id"], lead["id"], {
        "followup_count": attempt + 1,
        "last_contact_at": now_ms(),
        "next_followup_at": next_at,
    })
    repo.log_activity(tenant["id"], "followup",
                      f"Automated follow-up #{attempt + 1} sent", lead["id"])
    if next_at is None:
        repo.update_lead(tenant["id"], lead["id"], {"next_followup_at": None})
    return [message]


# ----------------------------------------------------------- transitions ----

def _book(tenant, lead, slot, turn=None):
    if not schedule.slot_is_available(tenant, slot["starts_at"], slot["ends_at"]):
        fresh = schedule.open_slots(tenant, count=3)
        body = ("Ah — that time was just taken. Here's what's still open:\n"
                + "\n".join(f"{i + 1}. {s['label']}" for i, s in enumerate(fresh))
                if fresh else
                "Ah — that time was just taken. The team will confirm the next opening shortly.")
        message = repo.add_message(tenant["id"], lead["id"], "ai", body,
                                   channel=deliver_to_lead(tenant, lead, body),
                                   meta={"offered_slots": bool(fresh)})
        return [message]

    value = _estimated_value(tenant, lead)
    appointment = repo.create_appointment(
        tenant["id"], lead["id"], slot["starts_at"], slot["ends_at"],
        service=lead.get("service_requested") or "", value=value)

    when = schedule.format_slot(slot["starts_at"], tenant)
    body = (f"You're booked for {when}. "
            f"{tenant['name']} will confirm by "
            f"{'text' if lead.get('phone') else 'email'} before the visit — see you then!")
    message = repo.add_message(tenant["id"], lead["id"], "ai", body,
                               channel=deliver_to_lead(tenant, lead, body),
                               meta={"appointment_id": appointment["id"]})
    lead = repo.update_lead(tenant["id"], lead["id"], {
        "status": "BOOKED", "score": "hot", "estimated_value": value,
        "last_contact_at": now_ms(), "next_followup_at": None,
    })
    repo.log_activity(tenant["id"], "booked", f"Appointment booked for {when}", lead["id"])
    notify_appointment_booked(tenant, lead, appointment)
    return [message]


def _opt_out(tenant, lead, turn):
    messages = []
    if turn.reply:
        messages.append(repo.add_message(tenant["id"], lead["id"], "ai", turn.reply,
                                         channel=deliver_to_lead(tenant, lead, turn.reply)))
    repo.update_lead(tenant["id"], lead["id"], {
        "opted_out": True, "ai_active": False, "status": "LOST",
        "close_reason": "Opted out", "next_followup_at": None,
    })
    repo.log_activity(tenant["id"], "opt_out", "Customer opted out — messaging stopped", lead["id"])
    return messages


def _closed_lost(tenant, lead, turn):
    messages = []
    if turn.reply:
        messages.append(repo.add_message(tenant["id"], lead["id"], "ai", turn.reply,
                                         channel=deliver_to_lead(tenant, lead, turn.reply)))
    repo.update_lead(tenant["id"], lead["id"], {
        "status": "LOST", "score": "cold", "close_reason": "Not interested",
        "next_followup_at": None,
    })
    repo.log_activity(tenant["id"], "lost", "Customer said they are not interested", lead["id"])
    return messages


def _out_of_area(tenant, lead, turn):
    messages = []
    if turn.reply:
        messages.append(repo.add_message(tenant["id"], lead["id"], "ai", turn.reply,
                                         channel=deliver_to_lead(tenant, lead, turn.reply)))
    repo.update_lead(tenant["id"], lead["id"], {
        "status": "LOST", "score": "cold", "close_reason": "Outside service area",
        "next_followup_at": None, "ai_active": False,
    })
    repo.log_activity(tenant["id"], "out_of_area", "Lead is outside the service area", lead["id"])
    repo.add_notification(tenant["id"], "handoff", "Lead outside service area",
                          f"{lead.get('name') or 'A lead'} is outside the configured service areas.",
                          lead["id"])
    return messages


def _handoff(tenant, lead, reason, turn=None):
    messages = []
    body = (turn.reply if turn and turn.reply else
            "Of course — I'm bringing someone from the team into this conversation now.")
    messages.append(repo.add_message(tenant["id"], lead["id"], "ai", body,
                                     channel=deliver_to_lead(tenant, lead, body)))
    lead = repo.update_lead(tenant["id"], lead["id"], {
        "ai_active": False, "next_followup_at": None, "last_contact_at": now_ms()})
    repo.log_activity(tenant["id"], "handoff", f"Handed to a human: {reason}", lead["id"])
    notify_handoff(tenant, lead, reason)
    return messages


def _exhausted(tenant, lead):
    repo.update_lead(tenant["id"], lead["id"], {
        "status": "NO_RESPONSE" if lead["status"] in ("NEW", "CONTACTED") else lead["status"],
        "next_followup_at": None,
        "close_reason": lead.get("close_reason") or "No response after all follow-ups",
    })
    repo.log_activity(tenant["id"], "no_response",
                      "Follow-up sequence finished with no reply", lead["id"])
    return []


# ------------------------------------------------------- manual controls ----

def send_human_message(tenant, lead, body, author_name=""):
    """Business owner replying by hand. Turns the AI off so it cannot talk over them."""
    body = (body or "").strip()[:2000]
    if not body:
        return None
    channel = deliver_to_lead(tenant, lead, body)
    message = repo.add_message(tenant["id"], lead["id"], "human", body, channel=channel,
                               meta={"author": author_name})
    repo.update_lead(tenant["id"], lead["id"], {
        "last_contact_at": now_ms(), "ai_active": False, "next_followup_at": None})
    repo.log_activity(tenant["id"], "human_reply", f"{author_name or 'Owner'} replied manually",
                      lead["id"])
    return message


def set_ai_active(tenant, lead, active):
    """Toggle between AI Active and Human Takeover. Re-enabling restarts the
    follow-up cadence so the lead does not go cold."""
    patch = {"ai_active": bool(active)}
    if active:
        patch["next_followup_at"] = _schedule_next_followup(
            tenant, lead["id"], int(lead["followup_count"] or 0))
    else:
        patch["next_followup_at"] = None
    updated = repo.update_lead(tenant["id"], lead["id"], patch)
    repo.log_activity(tenant["id"], "ai_toggle",
                      "Assistant re-activated" if active else "Human takeover enabled", lead["id"])
    return updated


def book_manually(tenant, lead, starts_at, ends_at, service="", notes=""):
    if not schedule.slot_is_available(tenant, starts_at, ends_at):
        raise ValueError("That time overlaps an existing appointment.")
    value = _estimated_value(tenant, lead)
    appointment = repo.create_appointment(tenant["id"], lead["id"], starts_at, ends_at,
                                          service=service or lead.get("service_requested") or "",
                                          value=value, notes=notes)
    lead = repo.update_lead(tenant["id"], lead["id"], {
        "status": "BOOKED", "score": "hot", "estimated_value": value, "next_followup_at": None})
    when = schedule.format_slot(starts_at, tenant)
    repo.log_activity(tenant["id"], "booked", f"Appointment booked manually for {when}", lead["id"])
    notify_appointment_booked(tenant, lead, appointment)
    return appointment
