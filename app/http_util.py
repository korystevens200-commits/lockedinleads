"""
Minimal request/response plumbing and a regex router on top of http.server.

Kept deliberately small: this project has no web framework dependency, so this
file is the whole "framework" — parsing, routing, JSON, cookies, headers.
"""

import json
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

MAX_BODY_BYTES = 256 * 1024   # generous for JSON payloads, small enough to bound memory


class HttpError(Exception):
    def __init__(self, status, message, code=None, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.extra = extra or {}


class Request:
    def __init__(self, method, path, query, headers, body, remote_ip):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.raw_body = body
        self.remote_ip = remote_ip
        self._json = None
        self.session = None       # populated by auth middleware
        self.user = None
        self.tenant_id = None     # the tenant this request is allowed to act on

    @property
    def json(self):
        if self._json is None:
            if not self.raw_body:
                self._json = {}
            else:
                try:
                    parsed = json.loads(self.raw_body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise HttpError(400, "Request body must be valid JSON.")
                self._json = parsed if isinstance(parsed, dict) else {"_": parsed}
        return self._json

    def q(self, name, default=None):
        values = self.query.get(name)
        return values[0] if values else default

    def cookie(self, name):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        morsel = jar.get(name)
        return morsel.value if morsel else None

    def header(self, name, default=None):
        return self.headers.get(name, default)


class Response:
    def __init__(self, status=200, body=b"", content_type="application/json",
                 headers=None, cookies=None):
        self.status = status
        self.body = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
        self.content_type = content_type
        self.headers = headers or {}
        self.cookies = cookies or []

    def set_cookie(self, name, value, max_age=None, http_only=True, secure=False,
                   same_site="Lax", path="/"):
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        self.cookies.append("; ".join(parts))
        return self


def json_response(data, status=200, headers=None):
    return Response(status, json.dumps(data, default=str).encode("utf-8"),
                    "application/json", headers)


def error_response(status, message, code=None, extra=None):
    payload = {"error": message}
    if code:
        payload["code"] = code
    if extra:
        payload.update(extra)
    return json_response(payload, status)


def no_content():
    return Response(204, b"", "application/json")


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler, **flags):
        regex = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method.upper(), regex, handler, flags))

    def get(self, pattern, **flags):
        return lambda fn: (self.add("GET", pattern, fn, **flags), fn)[1]

    def post(self, pattern, **flags):
        return lambda fn: (self.add("POST", pattern, fn, **flags), fn)[1]

    def patch(self, pattern, **flags):
        return lambda fn: (self.add("PATCH", pattern, fn, **flags), fn)[1]

    def delete(self, pattern, **flags):
        return lambda fn: (self.add("DELETE", pattern, fn, **flags), fn)[1]

    def match(self, method, path):
        path_matched = False
        for route_method, regex, handler, flags in self.routes:
            m = regex.match(path)
            if not m:
                continue
            path_matched = True
            if route_method == method.upper():
                return handler, m.groupdict(), flags
        if path_matched:
            raise HttpError(405, "Method not allowed for this endpoint.")
        return None, None, None


def parse_request(handler):
    """Build a Request from a BaseHTTPRequestHandler instance."""
    parsed = urlparse(handler.path)
    length = 0
    raw_len = handler.headers.get("Content-Length")
    if raw_len:
        try:
            length = int(raw_len)
        except ValueError:
            raise HttpError(400, "Invalid Content-Length header.")
    if length > MAX_BODY_BYTES:
        raise HttpError(413, "Request body too large.")
    body = handler.rfile.read(length) if length > 0 else b""

    # Behind a proxy (Fly, Render) the real client IP is in X-Forwarded-For.
    forwarded = handler.headers.get("X-Forwarded-For", "")
    remote_ip = forwarded.split(",")[0].strip() if forwarded else handler.client_address[0]

    return Request(handler.command, parsed.path, parse_qs(parsed.query),
                   handler.headers, body, remote_ip)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # Self-hosted assets only; Google Fonts is the single external origin.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}
