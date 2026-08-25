"""HTTP API routes."""

from ..http_util import Router

router = Router()

from . import admin_routes, auth_routes, billing_routes, client_routes, public_routes  # noqa: E402,F401
