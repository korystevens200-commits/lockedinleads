"""
Built-in conversation engine (no external model required).

This is a real fallback, not a stub: it runs the full flow — greet, qualify
against the tenant's own questions, check the service area, offer genuine open
slots, take the booking, detect opt-outs and hand off to a human. That is what
lets the product be demoed and even operated with zero credentials, and what
keeps leads answered if the model API is briefly unreachable.
"""

import random
import re

from .provider import AIProvider, AITurn

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")

OPT_OUT = ("stop", "unsubscribe", "do not contact", "don't contact", "remove me",
           "take me off", "opt out", "leave me alone")
NEGATIVE = ("not interested", "no thanks", "no thank you", "already booked", "found someone",
            "went with someone", "no longer need", "changed my mind")
AFFIRMATIVE = ("yes", "yep", "yeah", "yup", "sure", "ok", "okay", "sounds good", "works for me",
               "that works", "perfect", "book it", "let's do it", "lets do it", "confirmed",
               "please do", "go ahead", "great")
ORDINALS = {"1": 0, "one": 0, "first": 0, "2": 1, "two": 1, "second": 1, "3": 2, "three": 2, "third": 2}
DAY_WORDS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
             "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun")

DEFAULT_QUESTIONS = [
    {"field_key": "service_needed", "prompt": "What service are you looking for?",
     "answer_type": "text", "required": True, "options": []},
    {"field_key": "location", "prompt": "What area or address would we be servicing?",
     "answer_type": "text", "required": True, "options": []},
    {"field_key": "timing", "prompt": "When would you ideally like this done?",
     "answer_type": "text", "required": True, "options": []},
]


class RulesProvider(AIProvider):
    name = "rules"

    def available(self) -> bool:
        return True

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _questions(ctx):
        return ctx["questions"] or DEFAULT_QUESTIONS

    @staticmethod
    def _assistant(ctx):
        return ctx["settings"]["ai"]["assistant_name"]

    @staticmethod
    def _last_ai_meta(ctx):
        for msg in reversed(ctx["messages"]):
            if msg["role"] in ("ai", "human"):
                return msg.get("meta") or {}
        return {}

    @staticmethod
    def _in_service_area(ctx, text):
        """None when we cannot tell — only an explicit mismatch rejects a lead."""
        areas = [a["name"].lower() for a in ctx["areas"]]
        if not areas or not text:
            return None
        low = text.lower()
        if any(area in low for area in areas):
            return True
        # A place name we do not recognise only counts as a miss when the text
        # actually looks like a location.
        if len(low.split()) <= 8 and any(ch.isalpha() for ch in low):
            return False
        return None

    @staticmethod
    def _match_service(ctx, text):
        if not text:
            return ""
        low = text.lower()
        for svc in ctx["services"]:
            name = svc["name"].lower()
            if name in low or all(word in low for word in name.split() if len(word) > 3):
                return svc["name"]
        return ""

    def _next_question(self, ctx, answers):
        for q in self._questions(ctx):
            if q.get("required", True) and not answers.get(q["field_key"]):
                return q
        for q in self._questions(ctx):
            if not answers.get(q["field_key"]):
                return q
        return None

    @staticmethod
    def _slot_choice(text, slots, offered):
        """Which offered slot (if any) the customer just accepted."""
        if not slots or not text:
            return -1
        low = text.lower().strip()
        for token, index in ORDINALS.items():
            if re.search(rf"\b{re.escape(token)}\b", low) and index < len(slots):
                return index
        for i, slot in enumerate(slots):
            label = slot["label"].lower()
            day = label.split(" ")[0]
            time_part = label.split(" at ")[-1].replace(":00", "").replace(" ", "")
            if day and day in low and (time_part[:-2] in low.replace(" ", "") or ":" not in low):
                return i
            if time_part and time_part in low.replace(" ", "").replace(".", ""):
                return i
        if offered and any(re.search(rf"\b{re.escape(word)}\b", low) for word in AFFIRMATIVE):
            return 0
        return -1

    # -- main ---------------------------------------------------------------
    def generate(self, ctx, directive="reply", incoming=None) -> AITurn:
        lead = ctx["lead"]
        answers = dict(lead.get("qualification") or {})
        slots = ctx["slots"]
        meta = self._last_ai_meta(ctx)
        offered = bool(meta.get("offered_slots"))
        pending_key = meta.get("pending_key")
        text = (incoming or "").strip()
        low = text.lower()
        turn = AITurn(reply="", provider=self.name, score=lead.get("score") or "unscored")

        if directive == "opening":
            return self._opening(ctx, answers, turn)

        if directive == "followup":
            return self._followup(ctx, answers, slots, turn)

        # --- inbound message handling --------------------------------------
        if any(word in low for word in OPT_OUT):
            turn.intent = "opt_out"
            turn.reply = ("No problem at all — I've taken you off our list. "
                          f"If you ever need us, {ctx['tenant']['name']} is here. Take care!")
            return turn

        handoff_words = ctx["settings"]["ai"].get("handoff_keywords") or []
        if any(word and word in low for word in handoff_words) or "speak to someone" in low:
            turn.intent = "needs_human"
            turn.needs_human = True
            turn.reply = ("Absolutely — I'm passing you to someone from the team now. "
                          "They'll pick this up shortly.")
            return turn

        if any(phrase in low for phrase in NEGATIVE):
            turn.intent = "not_interested"
            turn.reply = ("Understood, thanks for letting me know! If anything changes, "
                          "just reply here and I'll take care of it.")
            return turn

        # Free-form extraction — people volunteer details out of order.
        email_match = EMAIL_RE.search(text)
        if email_match and not lead.get("email"):
            turn.lead_email = email_match.group(0)
        phone_match = PHONE_RE.search(text)
        if phone_match and not lead.get("phone") and len(re.sub(r"\D", "", phone_match.group(1))) >= 7:
            turn.lead_phone = phone_match.group(1).strip()
        service_guess = self._match_service(ctx, text)
        if service_guess:
            turn.service_interest = service_guess

        # Did they just accept one of the times we offered?
        choice = self._slot_choice(text, slots, offered)
        if offered and choice >= 0:
            turn.selected_slot_index = choice
            turn.intent = "booking_selected"
            turn.qualified = True
            turn.score = "hot"
            turn.qualification_updates = answers
            turn.reply = ""     # the engine writes the confirmation with the real time
            return turn

        # Record the answer to whatever we asked last.
        if pending_key and text:
            answers[pending_key] = text[:300]
            turn.qualification_updates[pending_key] = text[:300]
            if pending_key in ("location", "address", "service_area", "city", "zip"):
                turn.location = text[:160]
                if self._in_service_area(ctx, text) is False:
                    turn.intent = "out_of_area"
                    turn.score = "cold"
                    areas = ", ".join(a["name"] for a in ctx["areas"])
                    turn.reply = (f"Thanks! That looks like it may be outside our current service area"
                                  f"{f' ({areas})' if areas else ''}. I'll have the team confirm and "
                                  "reach out if we can cover it.")
                    return turn
            if pending_key in ("service_needed", "service", "service_type") and not turn.service_interest:
                turn.service_interest = text[:120]
            if pending_key in ("name", "full_name", "contact_name"):
                turn.lead_name = text[:120]

        if not lead.get("name") and not turn.lead_name and pending_key == "name":
            turn.lead_name = text[:120]

        question = self._next_question(ctx, answers)
        first_name = (turn.lead_name or lead.get("name") or "").split(" ")[0]

        if question:
            turn.intent = "gathering_info"
            turn.score = "warm"
            opener = random.choice(["Got it", "Perfect", "Great", "Thanks"])
            prefix = f"{opener}{', ' + first_name if first_name else ''}! "
            turn.reply = prefix + question["prompt"]
            if question.get("options"):
                turn.reply += " (" + " / ".join(question["options"][:4]) + ")"
            turn.pending_key = question["field_key"]
            return turn

        # Everything required is answered — go for the booking.
        turn.qualified = True
        turn.score = "hot"
        turn.intent = "ready_to_book"
        if slots and ctx["settings"]["booking"].get("enabled", True):
            listed = "\n".join(f"{i + 1}. {s['label']}" for i, s in enumerate(slots))
            turn.reply = (f"{'Perfect, ' + first_name if first_name else 'Perfect'} — I have everything "
                          f"I need. Here are the next openings:\n{listed}\n\nWhich works best? "
                          "Just reply with the number.")
            turn.offered_slots = True
        else:
            turn.reply = ("Thanks — I have everything I need. The team will confirm the next available "
                          "time and get right back to you.")
        return turn

    def _opening(self, ctx, answers, turn):
        tenant = ctx["tenant"]
        lead = ctx["lead"]
        cfg = ctx["settings"]["ai"]
        first_name = (lead.get("name") or "").split(" ")[0]
        greeting = cfg.get("custom_greeting") or ""
        if greeting:
            turn.reply = greeting.replace("{name}", first_name or "there").replace(
                "{business}", tenant["name"])
        else:
            hello = f"Hi {first_name}!" if first_name else "Hi there!"
            service = lead.get("service_requested")
            about = f" Thanks for reaching out about {service}." if service else " Thanks for reaching out."
            # Business names often end in "Co." — don't double the full stop.
            business = tenant["name"].rstrip(".")
            turn.reply = (f"{hello} This is {self._assistant(ctx)} from {business}.{about} "
                          "I can get you sorted in a couple of quick questions.")

        question = self._next_question(ctx, answers)
        if question:
            turn.reply += " " + question["prompt"]
            if question.get("options"):
                turn.reply += " (" + " / ".join(question["options"][:4]) + ")"
            turn.pending_key = question["field_key"]
        turn.intent = "gathering_info"
        turn.score = "warm"
        return turn

    def _followup(self, ctx, answers, slots, turn):
        lead = ctx["lead"]
        attempt = int(lead.get("followup_count") or 0)
        first_name = (lead.get("name") or "").split(" ")[0]
        hey = f"Hi {first_name}" if first_name else "Hi"
        tenant_name = ctx["tenant"]["name"]

        if slots and ctx["settings"]["booking"].get("enabled", True):
            slot = slots[0]["label"]
            options = [
                f"{hey} — just checking in. I still have {slot} open. Want me to hold it for you?",
                f"{hey}, following up from {tenant_name}. {slot} is still available — should I book it?",
                f"{hey} — last check from me. {slot} is open if you'd still like it. "
                "Otherwise I'll stop here and leave you to it.",
            ]
            turn.offered_slots = True
        else:
            options = [
                f"{hey} — just following up on your enquiry with {tenant_name}. Still interested?",
                f"{hey}, checking back in. Happy to answer any questions and get you scheduled.",
                f"{hey} — I'll leave this here for now. Reply any time and I'll pick it straight back up.",
            ]
        turn.reply = options[min(attempt, len(options) - 1)]
        turn.intent = "gathering_info"
        return turn
