"""
Test harness: boots a real server on a random port against a throwaway
database, and gives tests an HTTP client that behaves like a browser
(cookie jar + CSRF header).

Tests go through HTTP rather than calling functions directly, because the
security guarantees being tested — auth, CSRF, tenant isolation — live in the
request pipeline.
"""

import json
import os
import socket
import tempfile
import threading
import urllib.error
import urllib.request

_server = None
_thread = None
BASE_URL = None


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server():
    """Boot the app once for the whole suite."""
    global _server, _thread, BASE_URL
    if _server is not None:
        return BASE_URL

    port = _free_port()
    os.environ.update({
        "DB_PATH": os.path.join(tempfile.mkdtemp(prefix="lil-test-"), "test.db"),
        "PORT": str(port),
        "APP_ENV": "test",
        "SECRET_KEY": "test-secret-key-not-used-in-production",
        "PUBLIC_URL": f"http://127.0.0.1:{port}",
        "ADMIN_EMAIL": "admin@test.local",
        "ADMIN_PASSWORD": "admin-password-123",
        "SEED_DEMO": "true",
        "WORKER_ENABLED": "false",     # tests drive the worker explicitly
        "AI_PROVIDER": "rules",        # deterministic, no network
        "SMTP_HOST": "", "TWILIO_ACCOUNT_SID": "", "STRIPE_SECRET_KEY": "",
    })

    from app.server import create_server
    _server, _ = create_server()
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    BASE_URL = f"http://127.0.0.1:{port}"
    return BASE_URL


def stop_server():
    global _server
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None


class Client:
    """Minimal browser: keeps cookies, sends the CSRF header on writes."""

    def __init__(self):
        self.cookies = {}
        self.csrf = None

    def request(self, method, path, body=None, headers=None, raw_body=None):
        url = BASE_URL + path
        data = None
        request_headers = {"Accept": "application/json"}
        if raw_body is not None:
            data = raw_body
            request_headers["Content-Type"] = "application/json"
        elif body is not None:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        if self.cookies:
            request_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if self.csrf and method not in ("GET", "HEAD"):
            request_headers["X-CSRF-Token"] = self.csrf
        request_headers.update(headers or {})

        req = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                self._store_cookies(response)
                payload = response.read()
                return response.status, self._parse(payload), response.headers
        except urllib.error.HTTPError as exc:
            self._store_cookies(exc)
            return exc.code, self._parse(exc.read()), exc.headers

    @staticmethod
    def _parse(payload):
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return payload.decode("utf-8", "replace")

    def _store_cookies(self, response):
        for header in response.headers.get_all("Set-Cookie") or []:
            pair = header.split(";")[0]
            name, _, value = pair.partition("=")
            if value:
                self.cookies[name.strip()] = value.strip()
            else:
                self.cookies.pop(name.strip(), None)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body, **kw)

    def patch(self, path, body=None, **kw):
        return self.request("PATCH", path, body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def login(self, email, password):
        status, data, _ = self.post("/api/auth/login", {"email": email, "password": password})
        if status == 200:
            self.csrf = data["csrf_token"]
        return status, data
