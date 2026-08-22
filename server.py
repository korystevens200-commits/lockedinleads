#!/usr/bin/env python3
"""
LockedinLeads — demo backend.

Stdlib only (no pip installs needed). Serves the static site and a small
JSON API, persists leads to data/leads.json, runs a background follow-up
sweep thread, and sends (or simulates) an owner email when a lead qualifies.

Swap the storage layer for a real database and send_owner_email() for a
real provider (SES/SendGrid/Resend) at deploy time — every other file only
talks to the HTTP API below.
"""

import base64
import hmac
import json
import os
import re
import secrets
import smtplib
import threading
import time
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, 'data')
LEADS_FILE = os.path.join(DATA_DIR, 'leads.json')
EMAIL_LOG_FILE = os.path.join(DATA_DIR, 'email_log.jsonl')


def load_dotenv():
    """Tiny stdlib .env loader — keeps real secrets out of the codebase and
    out of chat. Create ai-lead-machine/.env (gitignored) with KEY=VALUE
    lines; existing environment variables always win."""
    path = os.path.join(ROOT, '.env')
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_dotenv()

PORT = int(os.environ.get('PORT', 8420))

BUSINESS_NAME = 'Sparkle & Shine Cleaning Co.'
OWNER_EMAIL = os.environ.get('OWNER_EMAIL', 'owner@example.com')
SMTP_HOST = os.environ.get('SMTP_HOST')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
SMTP_FROM = os.environ.get('SMTP_FROM', SMTP_USER or 'noreply@example.com')

DASHBOARD_USER = os.environ.get('DASHBOARD_USER', 'owner')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'changeme')

# Compressed for the demo so automation is visible live.
# Swap for 24h / a real scheduler (cron, Celery beat, etc.) at deploy time.
FOLLOWUP_DELAY_MS = 25000
MAX_FOLLOWUPS = 2
SWEEP_INTERVAL_S = 3

_lock = threading.RLock()
_leads = []  # in-memory, write-through to disk


def now_ms():
    return int(time.time() * 1000)


def seed_demo_data():
    now = now_ms()
    day = 86400000
    return [
        {
            'id': 'L' + uuid.uuid4().hex[:10],
            'name': 'Jenna Ortiz', 'phone': '(305) 555-0142', 'address': '4210 Biscayne Blvd, Miami, FL',
            'homeSize': '3br', 'cleaningType': 'deep', 'frequency': 'biweekly', 'preferredDate': 'Aug 26',
            'phoneConsent': True,
            'status': 'booked', 'score': 'hot', 'quote': 224, 'bookedSlot': 'Aug 26, 10:00 AM',
            'followUpCount': 0, 'createdAt': now - 2 * day, 'updatedAt': now - 2 * day,
            'lastActivityAt': now - 2 * day, 'lastFollowUpAt': None,
            'notifiedOwner': True, 'emailStatus': 'simulated', 'emailSentAt': now - 2 * day,
            'transcript': [
                {'ts': now - 2 * day, 'from': 'ai', 'text': "Hi! I'm Aria, Sparkle & Shine's virtual assistant. What's your name?"},
                {'ts': now - 2 * day, 'from': 'lead', 'text': 'Jenna Ortiz'},
                {'ts': now - 2 * day, 'from': 'ai', 'text': 'Great, Jenna! Booked for Aug 26, 10:00 AM. See you then!'},
            ],
        },
        {
            'id': 'L' + uuid.uuid4().hex[:10],
            'name': 'Marcus Lee', 'phone': '(786) 555-0198', 'address': '900 Alton Rd, Miami Beach, FL',
            'homeSize': '2br', 'cleaningType': 'standard', 'frequency': 'monthly', 'preferredDate': 'Aug 29',
            'phoneConsent': True,
            'status': 'needs-follow-up', 'score': 'warm', 'quote': 117, 'bookedSlot': None,
            'followUpCount': 1, 'createdAt': now - day, 'updatedAt': now - 3600000,
            'lastActivityAt': now - 3600000, 'lastFollowUpAt': now - 3600000,
            'notifiedOwner': True, 'emailStatus': 'simulated', 'emailSentAt': now - day,
            'transcript': [
                {'ts': now - day, 'from': 'ai', 'text': "Hi! I'm Aria, Sparkle & Shine's virtual assistant. What's your name?"},
                {'ts': now - day, 'from': 'lead', 'text': 'Marcus Lee'},
                {'ts': now - 3600000, 'from': 'system', 'text': 'Automated follow-up sent to (737) 555-0198: "Hi Marcus, still want to lock in Aug 29?"'},
            ],
        },
        {
            'id': 'L' + uuid.uuid4().hex[:10],
            'name': 'Priya Nair', 'phone': '(305) 555-0176', 'address': '1500 Ponce De Leon Blvd, Coral Gables, FL',
            'homeSize': '4br+', 'cleaningType': 'move-in-out', 'frequency': 'one-time', 'preferredDate': 'Sep 2',
            'phoneConsent': True,
            'status': 'qualified', 'score': 'warm', 'quote': 320, 'bookedSlot': None,
            'followUpCount': 0, 'createdAt': now - 3600000, 'updatedAt': now - 3600000,
            'lastActivityAt': now - 3600000, 'lastFollowUpAt': None,
            'notifiedOwner': True, 'emailStatus': 'simulated', 'emailSentAt': now - 3600000,
            'transcript': [
                {'ts': now - 3600000, 'from': 'ai', 'text': "Hi! I'm Aria, Sparkle & Shine's virtual assistant. What's your name?"},
                {'ts': now - 3600000, 'from': 'lead', 'text': 'Priya Nair'},
            ],
        },
    ]


def load():
    global _leads
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, 'r') as f:
            _leads = json.load(f)
    else:
        _leads = seed_demo_data()
        persist()


def persist():
    tmp = LEADS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(_leads, f, indent=2)
    os.replace(tmp, LEADS_FILE)


def find(lead_id):
    for l in _leads:
        if l['id'] == lead_id:
            return l
    return None


def send_owner_email(lead):
    """Sends a real email if SMTP env vars are set, otherwise logs a
    clearly-labeled simulated email so the demo still shows the mechanism."""
    subject = f"New qualified lead: {lead.get('name') or 'Unknown'} ({lead.get('score', '')})"
    body = (
        f"New lead from {BUSINESS_NAME}\n\n"
        f"Name: {lead.get('name')}\n"
        f"Phone: {lead.get('phone')}\n"
        f"Address: {lead.get('address')}\n"
        f"Home size: {lead.get('homeSize')}\n"
        f"Cleaning type: {lead.get('cleaningType')}\n"
        f"Frequency: {lead.get('frequency')}\n"
        f"Preferred date: {lead.get('preferredDate')}\n"
        f"Quote: ${lead.get('quote')}\n"
        f"Score: {lead.get('score')}\n\n"
        f"View in dashboard: http://localhost:{PORT}/dashboard.html"
    )

    configured = all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, OWNER_EMAIL])
    entry = {
        'ts': now_ms(),
        'leadId': lead['id'],
        'to': OWNER_EMAIL,
        'subject': subject,
        'body': body,
    }

    if not configured:
        entry['status'] = 'simulated'
        entry['note'] = 'No SMTP_HOST/SMTP_USER/SMTP_PASSWORD/OWNER_EMAIL configured — logged instead of sent.'
        print(f"[SIMULATED EMAIL] to={OWNER_EMAIL} subject={subject!r}")
        _log_email(entry)
        return 'simulated'

    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = OWNER_EMAIL
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        entry['status'] = 'sent'
        _log_email(entry)
        print(f"[EMAIL SENT] to={OWNER_EMAIL} subject={subject!r}")
        return 'sent'
    except Exception as e:
        entry['status'] = 'failed'
        entry['error'] = str(e)
        _log_email(entry)
        print(f"[EMAIL FAILED] {e}")
        return 'failed'


def _log_email(entry):
    with open(EMAIL_LOG_FILE, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def sweep_once():
    """Background follow-up automation: nudges leads that stalled after
    qualifying but before booking. Runs regardless of whether any browser
    tab is open."""
    changed = False
    now = now_ms()
    with _lock:
        for lead in _leads:
            stalled = lead['status'] in ('qualified', 'needs-follow-up')
            if not stalled:
                continue
            if lead.get('followUpCount', 0) >= MAX_FOLLOWUPS:
                continue
            if now - lead.get('lastActivityAt', now) < FOLLOWUP_DELAY_MS:
                continue

            lead['status'] = 'needs-follow-up'
            lead['followUpCount'] = lead.get('followUpCount', 0) + 1
            lead['lastFollowUpAt'] = now
            lead['lastActivityAt'] = now
            lead['updatedAt'] = now
            first_name = (lead.get('name') or 'there').split(' ')[0]
            if lead['followUpCount'] == 1:
                text = (
                    f"Automated follow-up sent to {lead.get('phone')}: \"Hi {first_name}, it's "
                    f"{BUSINESS_NAME}! Still want to lock in {lead.get('preferredDate')}? "
                    f"Reply YES to grab the spot.\""
                )
            else:
                text = (
                    f"Second automated follow-up sent to {lead.get('phone')}: "
                    f"\"Just checking in one more time — happy to answer any questions before you book!\""
                )
            lead.setdefault('transcript', []).append({'ts': now, 'from': 'system', 'text': text})
            changed = True
        if changed:
            persist()
    return changed


def sweep_loop():
    while True:
        time.sleep(SWEEP_INTERVAL_S)
        try:
            sweep_once()
        except Exception as e:
            print(f"[sweep error] {e}")


def maybe_notify_owner(lead, was_notified_before):
    if was_notified_before:
        return
    if lead['status'] in ('qualified', 'booked'):
        status = send_owner_email(lead)
        lead['notifiedOwner'] = True
        lead['emailStatus'] = status
        lead['emailSentAt'] = now_ms()


# ---------------------------------------------------------------- HTTP ----

ID_RE = re.compile(r'^/api/leads/([^/]+)(?:/(transcript|followup))?$')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw or b'{}')

    def _is_authorized(self):
        header = self.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode('utf-8')
            user, _, pw = decoded.partition(':')
        except Exception:
            return False
        return hmac.compare_digest(user, DASHBOARD_USER) and hmac.compare_digest(pw, DASHBOARD_PASSWORD)

    def _require_auth(self):
        """Gate owner-only views (dashboard page, full lead list, manual
        follow-up) behind HTTP Basic Auth. The customer-facing chat widget
        never calls these, so this doesn't block real leads from booking."""
        if self._is_authorized():
            return True
        body = b'Authentication required'
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="LockedinLeads Dashboard"')
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/dashboard.html', '/api/leads') or ID_RE.match(parsed.path):
            if not self._require_auth():
                return
        if parsed.path == '/api/leads':
            with _lock:
                data = sorted(_leads, key=lambda l: l['createdAt'], reverse=True)
            self._send_json(data)
            return
        m = ID_RE.match(parsed.path)
        if m and m.group(2) is None:
            with _lock:
                lead = find(m.group(1))
            if lead is None:
                self._send_json({'error': 'not found'}, 404)
            else:
                self._send_json(lead)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/leads':
            body = self._read_json()
            now = now_ms()
            lead = {
                'id': 'L' + uuid.uuid4().hex[:10],
                'name': '', 'phone': '', 'address': '', 'homeSize': '',
                'cleaningType': '', 'frequency': '', 'preferredDate': '',
                'phoneConsent': False,
                'status': 'new', 'score': 'pending', 'quote': None, 'bookedSlot': None,
                'transcript': [], 'followUpCount': 0,
                'lastActivityAt': now, 'lastFollowUpAt': None,
                'notifiedOwner': False, 'emailStatus': None, 'emailSentAt': None,
                'createdAt': now, 'updatedAt': now,
            }
            lead.update(body)
            with _lock:
                _leads.append(lead)
                persist()
            self._send_json(lead, 201)
            return

        m = ID_RE.match(parsed.path)
        if m and m.group(2) == 'transcript':
            entry = self._read_json()
            with _lock:
                lead = find(m.group(1))
                if lead is None:
                    self._send_json({'error': 'not found'}, 404)
                    return
                entry['ts'] = now_ms()
                lead.setdefault('transcript', []).append(entry)
                lead['lastActivityAt'] = entry['ts']
                lead['updatedAt'] = entry['ts']
                persist()
            self._send_json(lead)
            return

        if m and m.group(2) == 'followup':
            if not self._require_auth():
                return
            with _lock:
                lead = find(m.group(1))
                if lead is None:
                    self._send_json({'error': 'not found'}, 404)
                    return
                now = now_ms()
                lead['status'] = 'needs-follow-up'
                lead['followUpCount'] = lead.get('followUpCount', 0) + 1
                lead['lastFollowUpAt'] = now
                lead['lastActivityAt'] = now
                lead['updatedAt'] = now
                first_name = (lead.get('name') or 'there').split(' ')[0]
                lead.setdefault('transcript', []).append({
                    'ts': now, 'from': 'system',
                    'text': f"Manual follow-up sent to {lead.get('phone')}: \"Hi {first_name}, just "
                            f"following up on your cleaning quote — happy to answer questions or lock in a date!\"",
                })
                persist()
            self._send_json(lead)
            return

        self._send_json({'error': 'not found'}, 404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        m = ID_RE.match(parsed.path)
        if m and m.group(2) is None:
            patch = self._read_json()
            with _lock:
                lead = find(m.group(1))
                if lead is None:
                    self._send_json({'error': 'not found'}, 404)
                    return
                was_notified = lead.get('notifiedOwner', False)
                lead.update(patch)
                lead['updatedAt'] = now_ms()
                maybe_notify_owner(lead, was_notified)
                persist()
            self._send_json(lead)
            return
        self._send_json({'error': 'not found'}, 404)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()


def main():
    load()
    print(f"Loaded {len(_leads)} lead(s) from {LEADS_FILE}")
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        print("SMTP not configured — owner emails will be simulated (logged to data/email_log.jsonl).")
        print("  To send real email, set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, OWNER_EMAIL.")
    if DASHBOARD_PASSWORD == 'changeme':
        print("WARNING: DASHBOARD_PASSWORD is still the default 'changeme' — set a real "
              "DASHBOARD_USER/DASHBOARD_PASSWORD before deploying anywhere public.")

    t = threading.Thread(target=sweep_loop, daemon=True)
    t.start()

    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f"LockedinLeads demo running at http://localhost:{PORT}")
    print(f"  Storefront: http://localhost:{PORT}/index.html")
    print(f"  Dashboard:  http://localhost:{PORT}/dashboard.html  (user: {DASHBOARD_USER})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
