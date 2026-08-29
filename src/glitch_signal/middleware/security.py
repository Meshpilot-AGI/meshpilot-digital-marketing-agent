"""Security response headers (CF hardening, mirrors leaselens app/security.py).

Adds standard hardening headers to every response. `setdefault` so a handler that sets
its own value wins. HSTS is safe: the API is HTTPS-only in prod (FastAPI Cloud + Cloudflare).
"""
from __future__ import annotations

from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
        return response
