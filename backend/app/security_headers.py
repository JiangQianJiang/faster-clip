"""Security headers middleware for CSP and other response headers."""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Production CSP
_CSP_PROD = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' blob: data:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)

# Development CSP (allows Vite HMR)
_CSP_DEV = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' blob: data:; "
    "media-src 'self' blob:; "
    "connect-src 'self' ws://localhost:3000; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _get_csp() -> str:
    """Return CSP based on environment."""
    is_dev = os.getenv("DEBUG", "false").lower() == "true"
    return _CSP_DEV if is_dev else _CSP_PROD


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Set CSP
        response.headers["Content-Security-Policy"] = _get_csp()

        # Set other security headers
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        return response
