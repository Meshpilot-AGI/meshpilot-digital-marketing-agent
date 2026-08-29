"""Origin shared-secret gate (CF hardening, mirrors leaselens app/originauth.py).

Cloudflare (once api.meshpilot.app is proxied) injects a shared-secret request header via
a Transform Rule. This middleware requires that header on the sensitive action paths
(`/internal/*`, `/jobs/*`) so a client that reaches the FastAPI Cloud **origin** directly —
bypassing Cloudflare, and with it the WAF/rate-limit — is rejected with 403.

Design (nothing breaks):
- **Fail-open**: if no secret is configured the gate is DISABLED, so a missing env var can
  never cause a self-inflicted outage. Enforcement turns on only once `ORIGIN_SHARED_SECRET`
  is set AND Cloudflare is injecting the matching header (`operation: set`, so a client can't
  smuggle a guessed value through the edge — it's overwritten there).
- Only `/internal/*` + `/jobs/*` are gated. `/healthz` (FastAPI Cloud platform probes hit the
  origin directly), `/oauth/*` (user-browser callbacks), and `/media/fetch` (HMAC-signed;
  external partners fetch it) stay open.
- Constant-time comparison. Raw ASGI so the reject happens before the handler runs.
"""
from __future__ import annotations

import hmac
import json
from typing import Any

_GATED_PREFIXES = ("/internal", "/jobs")


class OriginAuthMiddleware:
    def __init__(self, app: Any, *, secret: str | None, header: str = "x-origin-auth") -> None:
        self.app = app
        self.secret = secret or None
        self._secret_bytes = self.secret.encode() if self.secret else b""
        self.header = header.lower().encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self.secret:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith(_GATED_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        provided = headers.get(self.header, b"")
        if hmac.compare_digest(provided, self._secret_bytes):
            await self.app(scope, receive, send)
            return
        await self._reject(send)

    async def _reject(self, send: Any) -> None:
        body = json.dumps({"detail": "Forbidden."}).encode()
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
