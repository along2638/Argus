"""CSRF protection middleware — double-submit cookie pattern."""

import secrets
import hmac
import hashlib
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Paths that are exempt from CSRF checks (GET, OPTIONS, and public endpoints)
_EXEMPT_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
    "/static/",
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi",
    "/ws/",
)

# Methods that need CSRF protection (state-changing)
_PROTECTED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    Flow:
    1. Client gets a csrf_token cookie (set on first GET to /csrf-token)
    2. Client sends the token in X-CSRF-Token header on state-changing requests
    3. Server compares cookie value with header value using constant-time comparison
    """

    async def dispatch(self, request: Request, call_next):
        # Skip non-state-changing methods
        if request.method not in _PROTECTED_METHODS:
            response = await call_next(request)
            # Set CSRF cookie on GET requests if not present
            if request.method == "GET" and not request.cookies.get("csrf_token"):
                token = secrets.token_hex(32)
                response.set_cookie(
                    key="csrf_token",
                    value=token,
                    max_age=3600,
                    httponly=False,  # Must be readable by JavaScript
                    samesite="strict",
                    path="/",
                )
            return response

        # Skip exempt paths
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Skip if no auth cookie (API-only requests with Bearer token)
        if not request.cookies.get("token"):
            return await call_next(request)

        # Validate CSRF token
        cookie_token = request.cookies.get("csrf_token", "")
        header_token = request.headers.get("X-CSRF-Token", "")

        if not cookie_token or not header_token:
            logger.warning("csrf_missing", path=path)
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing"},
            )

        if not hmac.compare_digest(cookie_token, header_token):
            logger.warning("csrf_mismatch", path=path)
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token invalid"},
            )

        return await call_next(request)
