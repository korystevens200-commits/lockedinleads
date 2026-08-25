# LockedinLeads

AI lead response, qualification, follow-up and appointment booking for local
service businesses — sold and operated as an agency.

**The promise:** every lead gets an instant response, qualification, follow-up
and a booking attempt, 24/7.

**The metric everything is optimised for:** appointments booked.

---

## Quick start

```bash
python3 server.py
```

That is the whole install. No build step, no database server, no npm.
The app runs on the Python 3.11+ standard library; the only optional dependency
is the Anthropic SDK, used when you supply an API key.

On first boot it prints an agency admin email and a generated password **once**.
Save them, then open:

| | |
|---|---|
| Marketing site | http://localhost:8420/ |
| Sign in | http://localhost:8420/login.html |
| Agency console | http://localhost:8420/admin/ |
| Demo client login | `demo@lockedinleads.local` / `demodemo123` |

The demo account is a fully populated cleaning company showing the whole
journey — NEW → AI RESPONSE → QUALIFICATION → FOLLOW-UP → BOOKING → CUSTOMER —
so you can sell before you have a client.

To use a live Claude model:

```bash
pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
python3 server.py
```

---

## What runs without any credentials

Nothing is a stub. With an empty `.env` the whole product works:

| Capability | With credentials | Without |
|---|---|---|
| Conversations | Claude (`claude-opus-5`) | Built-in rules engine — asks your questions, checks the service area, offers real slots, takes the booking |
| Owner email alerts | Real SMTP send | Recorded as "simulated" and shown in the dashboard |
| Lead SMS | Twilio | Recorded as "simulated" |
| Billing | Stripe Checkout | Plan changes recorded locally, no card charged |

That is what makes the demo demoable and keeps leads answered if the model API
is briefly unreachable — a failed AI call falls back to the rules engine rather
than leaving a customer unanswered.

---

## Architecture

Deliberately modular, and deliberately dependency-light.

```
server.py                  entrypoint
app/
  config.py                every credential, read from the environment
  db.py                    SQLite schema + connections (WAL, per-thread)
  repo.py                  ALL data access — every call is tenant-scoped
  security.py              scrypt hashing, tokens, rate limiting, validation
  auth.py                  sessions, roles, CSRF, tenant resolution
  metrics.py               dashboard + reporting aggregates
  settings_schema.py       tenant settings defaults & validation
  seed.py                  first-boot bootstrap + the demo account
  server.py                HTTP server, static files, security headers
  http_util.py             request/response/router (the whole "framework")
  ai/
    provider.py            provider interface + resolution
    prompt.py              system prompt built from tenant configuration
    anthropic_provider.py  Claude (SDK imported lazily)
    rules_provider.py      built-in conversation engine
    engine.py              lead lifecycle: respond, qualify, follow up, book
  automation/
    schedule.py            business hours + real booking availability
    worker.py              background follow-up sweep
  notifications/           email, SMS, in-dashboard alerts
  billing/                 plan catalogue + Stripe (with mock mode)
  integrations/            webhook payload normalisation
  routes/                  public, auth, client, admin, billing endpoints
web/                       static frontend (no build step)
  css/                     design tokens + components
  js/                      one module per screen
tests/                     end-to-end test suite
```

**Swapping a piece.** The AI provider is the clearest example: add a class to
`app/ai/`, return it from `get_provider()`, set `AI_PROVIDER`. Nothing else in
the codebase talks to a model. Storage, notifications and billing are isolated
the same way.

### What the AI is given, and what it may not do

`app/ai/prompt.py` assembles the business name, industry, timezone, business
hours, services (with only the pricing notes the owner wrote), service areas,
qualification questions, the lead record, the conversation so far, and the real
open appointment slots computed by `app/automation/schedule.py`.

It is then explicitly forbidden from inventing pricing, availability, policies
or services. If it cannot answer from that context it says it will confirm with
the business, flags the conversation, and keeps working toward a booking. Slots
are re-checked for availability before an appointment is confirmed, so two leads
cannot claim the same time.

---

## Security

- **Passwords** — `hashlib.scrypt` with a per-user salt. Never reversible.
- **Sessions** — random tokens, stored hashed, in `HttpOnly` `SameSite=Lax`
  cookies; `Secure` when `APP_ENV=production`.
- **CSRF** — every state-changing request must echo the session's CSRF token in
  an `X-CSRF-Token` header, which a cross-origin page cannot read.
- **Tenant isolation** — a client user's tenant comes from their user row, never
  from a request parameter. Passing another tenant's id returns 403. Agency
  admins reach a client only through an explicit, server-recorded "acting
  tenant". This is enforced in one place: `auth.resolve_tenant()`.
- **Roles** — `agency_admin`, `owner`, `staff`. Staff cannot touch billing or
  API keys.
- **API keys** — stored as SHA-256 hashes with a display prefix; the full key is
  shown exactly once, on creation.
- **Webhooks** — the API key identifies the tenant, so a payload can never be
  routed to a business that did not issue the key. Payloads are size-capped,
  depth-capped, field-capped, validated and normalised before anything is
  written. Stripe webhooks verify the HMAC signature and timestamp window.
- **Rate limiting** — sign-in (per IP *and* per email), public lead forms,
  webhooks and the chat widget.
- **Headers** — CSP, `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`. No CORS allowance: same-origin only.
- **Static files** — paths are normalised and confined to `web/`; traversal is
  rejected.
- **Errors** — stack traces are logged server-side and never returned.
- **Secrets** — read from the environment only. The sole key the browser ever
  sees is the Stripe *publishable* key, which is designed to be public.

Run the test suite for the checks that assert all of this.

---

## Lead sources

Every route below fires the instant response the moment a lead lands.

| Source | How |
|---|---|
| Website form | `POST /api/public/leads/<your-slug>` — no key needed |
| Chat widget | `/chat.html?b=<your-slug>` |
| Facebook / Instagram / Google lead ads, Zapier, CRM | `POST /api/webhooks/leads` with an `X-API-Key` header |
| Phone calls, walk-ins | Manual entry in the dashboard |

Payload shapes from Facebook, Google Ads, Typeform, JotForm, WPForms, Zapier and
plain JSON are all understood — fields are mapped automatically. A lead needs at
least a valid phone number or email; anything else is rejected and logged.

```bash
curl -X POST https://your-domain/api/webhooks/leads \
  -H "X-API-Key: lil_live_..." \
  -H "Content-Type: application/json" \
  -d '{"name":"Jenna Ortiz","phone":"(305) 555-0142","service":"Deep Clean","city":"Coral Gables"}'
```

---

## Pricing & billing

Plans live in the database and are edited in the agency console under **Plans** —
the marketing site, client billing and MRR all read from there. Nothing is
hardcoded. Seeded defaults: Starter $1,000 setup + $1,000/mo, Growth $1,500 +
$1,500/mo, Pro $2,500 + $2,500/mo.

To take real payments: set `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` and
`STRIPE_WEBHOOK_SECRET`, create prices in Stripe, and paste the price IDs into
each plan. Point a Stripe webhook at `POST /api/webhooks/stripe`.

---

## Onboarding a new client

1. Agency console → **+ Client**. Set the business, plan and an owner login.
2. Send them the login. They land in a 7-step wizard: business info, services,
   service areas, qualification questions, booking availability, lead sources,
   and a live test conversation.
3. Finishing it flips the account to **active** and shows
   *"Your LockedinLeads system is ready."*

Everything in that wizard stays editable afterwards under **Automation**.

---

## Testing

```bash
python3 -m tests.run_tests
```

Covers authentication, tenant isolation, CSRF, rate limiting, webhook
validation, the full AI conversation flow, booking and double-booking, the
follow-up sequence and its stop rules, opt-out handling, reporting maths, and a
check that no secret is exposed through any endpoint.

---

## Deploying

Any host that runs a container. SQLite means **one machine plus a persistent
volume** — do not scale horizontally without moving to a networked database.

```bash
fly volumes create lockedinleads_data --size 1
fly secrets set SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")
fly secrets set PUBLIC_URL=https://your-app.fly.dev
fly deploy
```

Set `APP_ENV=production` (already in `fly.toml`) — the app refuses to start in
production without `SECRET_KEY`, and turns on secure cookies.

Back up by copying the SQLite file from the volume.

---

## Configuration

Every setting, with defaults and notes, is documented in `.env.example`.
