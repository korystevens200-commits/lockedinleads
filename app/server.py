"""
HTTP server: static frontend + JSON API on one port.

Deliberately stdlib-only. ThreadingHTTPServer plus SQLite in WAL mode handles
the load a lead-response product actually sees, with no framework to install,
no build step, and a single process to deploy.
"""

import json
import mimetypes
import os
import posixpath
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import auth, config, db, seed
from .automation import worker
from .http_util import (SECURITY_HEADERS, HttpError, Response, error_response, parse_request)
from .routes import router

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")

# Hashed/immutable assets could be cached hard; these are not, so keep it short
# and let the browser revalidate.
STATIC_CACHE = "public, max-age=300"
HTML_CACHE = "no-cache"


class Handler(BaseHTTPRequestHandler):
    server_version = "LockedinLeads"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if config.ENV != "test":
            print(f"{self.address_string()} - {fmt % args}")

    # -- dispatch -----------------------------------------------------------
    def _handle(self):
        try:
            req = parse_request(self)
        except HttpError as exc:
            return self._send(error_response(exc.status, exc.message, exc.code))
        except Exception:
            traceback.print_exc()
            return self._send(error_response(400, "Malformed request."))

        if req.path.startswith("/api/"):
            return self._send(self._dispatch_api(req))
        if req.method in ("GET", "HEAD"):
            return self._send(self._serve_static(req))
        return self._send(error_response(405, "Method not allowed."))

    def _dispatch_api(self, req):
        try:
            handler, params, _flags = router.match(req.method, req.path)
            if handler is None:
                return error_response(404, "Unknown endpoint.")
            auth.authenticate(req)
            auth.verify_csrf(req)
            response = handler(req, **params)
            return response if isinstance(response, Response) else error_response(
                500, "Handler returned an invalid response.")
        except HttpError as exc:
            return error_response(exc.status, exc.message, exc.code, exc.extra)
        except Exception:
            # Log the detail, return a generic message: stack traces must never
            # reach a client.
            print(f"[error] {req.method} {req.path}")
            traceback.print_exc()
            return error_response(500, "Something went wrong on our end. Please try again.")
        finally:
            pass

    # -- static -------------------------------------------------------------
    def _resolve_path(self, url_path):
        """Map a URL to a file inside web/, rejecting traversal attempts."""
        path = unquote(urlparse(url_path).path)
        path = posixpath.normpath(path).lstrip("/")
        if path in ("", "."):
            path = "index.html"
        if path.endswith("/"):
            path += "index.html"
        full = os.path.normpath(os.path.join(config.WEB_DIR, path))
        web_root = os.path.normpath(config.WEB_DIR)
        if not (full == web_root or full.startswith(web_root + os.sep)):
            return None
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full) and not os.path.splitext(full)[1]:
            candidate = full + ".html"
            if os.path.isfile(candidate):
                full = candidate
        return full if os.path.isfile(full) else None

    def _serve_static(self, req):
        full = self._resolve_path(req.path)
        if full is None:
            not_found = os.path.join(config.WEB_DIR, "404.html")
            if os.path.isfile(not_found):
                with open(not_found, "rb") as fh:
                    return Response(404, fh.read(), "text/html; charset=utf-8",
                                    {"Cache-Control": HTML_CACHE})
            return Response(404, b"Not found", "text/plain")
        ctype, _ = mimetypes.guess_type(full)
        ctype = ctype or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            body = fh.read()
        cache = HTML_CACHE if full.endswith(".html") else STATIC_CACHE
        return Response(200, body, ctype, {"Cache-Control": cache})

    # -- output -------------------------------------------------------------
    def _send(self, response):
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            for key, value in response.headers.items():
                self.send_header(key, value)
            for cookie in response.cookies:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_PUT = _handle
    do_DELETE = _handle

    def do_OPTIONS(self):
        # Same-origin app: no CORS allowance is granted by design.
        self._send(Response(204, b"", "text/plain", {"Allow": "GET, POST, PATCH, DELETE, OPTIONS"}))


def _startup_banner(admin_password):
    status = config.integration_status()
    print("\n" + "=" * 62)
    print(f"  {config.AGENCY_NAME} — running at {config.PUBLIC_URL}")
    print("=" * 62)
    print(f"  Marketing site : {config.PUBLIC_URL}/")
    print(f"  Sign in        : {config.PUBLIC_URL}/login.html")
    print(f"  Agency console : {config.PUBLIC_URL}/admin/")
    demo_exists = bool(__import__("app.repo", fromlist=["repo"]).get_tenant_by_slug("demo"))
    if demo_exists:
        print(f"  Demo account   : demo@lockedinleads.local / demodemo123")
    print("-" * 62)
    for key, label in (("ai", "AI"), ("email", "Email"), ("sms", "SMS"), ("billing", "Billing")):
        info = status[key]
        mark = "live" if info["configured"] else "simulated"
        print(f"  {label:<8}: {mark:<10} ({info.get('model') or info['provider']})")
    print("-" * 62)
    if admin_password:
        print(f"  AGENCY ADMIN CREATED")
        print(f"    email    : {config.ADMIN_EMAIL}")
        print(f"    password : {admin_password}")
        print("    ^ shown once. Set ADMIN_EMAIL/ADMIN_PASSWORD in .env to control this.")
        print("-" * 62)
    if not config.IS_PRODUCTION:
        print("  APP_ENV is not 'production' — SECRET_KEY is ephemeral and cookies")
        print("  are not Secure. Set APP_ENV=production and SECRET_KEY before deploying.")
        print("=" * 62 + "\n")
    else:
        print("=" * 62 + "\n")


def create_server():
    db.init()
    admin_password = seed.bootstrap()
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    httpd.daemon_threads = True
    return httpd, admin_password


def main():
    httpd, admin_password = create_server()
    worker.start()
    _startup_banner(admin_password)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
