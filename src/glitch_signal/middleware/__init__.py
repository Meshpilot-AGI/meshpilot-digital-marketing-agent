"""HTTP middleware — Cloudflare/origin hardening (mirrors leaselens app/*).

Order (add inner→outer; Starlette runs the LAST-added outermost):
    SecurityHeaders (inner) → CORS → TrustedHost → RateLimit → BodySizeLimit
    → OriginAuth (outer — rejects direct-to-origin /internal|/jobs first).
Wired in `glitch_signal.server`.
"""
from __future__ import annotations

from glitch_signal.middleware.bodylimit import BodySizeLimitMiddleware
from glitch_signal.middleware.originauth import OriginAuthMiddleware
from glitch_signal.middleware.ratelimit import RateLimitMiddleware, client_ip
from glitch_signal.middleware.security import SecurityHeadersMiddleware

__all__ = [
    "SecurityHeadersMiddleware",
    "BodySizeLimitMiddleware",
    "OriginAuthMiddleware",
    "RateLimitMiddleware",
    "client_ip",
]
