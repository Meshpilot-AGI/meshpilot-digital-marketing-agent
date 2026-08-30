"""In-process sliding-window rate limiter (CF hardening, mirrors leaselens app/ratelimit.py).

A per-instance **speed bump, NOT the security control**: on a multi-instance host the
effective ceiling is `limit x instances` and it resets on deploy. The real global enforcer
is the Cloudflare WAF once api.meshpilot.app is proxied. The constant-keyed global backstop
(`"all"`) is the in-app cost ceiling that XFF spoofing can't unlock.
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class SlidingWindowLimiter:
    """Allow at most `limit` events per `window_seconds` per key (LRU-bounded)."""

    def __init__(self, limit: int, window_seconds: float, *, max_keys: int = 20_000) -> None:
        self.limit = int(limit)
        self.window = float(window_seconds)
        self.max_keys = int(max_keys)
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _prune(self, dq: deque[float], now: float) -> None:
        cutoff = now - self.window
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def allow(self, key: str) -> bool:
        now = self._now()
        with self._lock:
            dq = self._hits.get(key)
            if dq is None:
                dq = deque()
                self._hits[key] = dq
                if len(self._hits) > self.max_keys:
                    self._hits.popitem(last=False)
            else:
                self._hits.move_to_end(key)
            self._prune(dq, now)
            if len(dq) >= self.limit:
                return False
            dq.append(now)
            return True

    def retry_after(self, key: str) -> int:
        now = self._now()
        with self._lock:
            dq = self._hits.get(key)
            if not dq:
                return 0
            self._prune(dq, now)
            if len(dq) < self.limit:
                return 0
            return max(1, int(self.window - (now - dq[0])) + 1)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Any) -> str:
    """Best-effort client IP for the rate-limit key (NOT a security control).

    Behind Cloudflare the true client is `CF-Connecting-IP` (CF overwrites it at the edge,
    so it isn't client-forgeable once proxied). Fall back to the rightmost XFF hop (nearest
    proxy appends the real client; leftmost is spoofable), then the socket peer.
    """
    # Only trust proxy-supplied client headers when we KNOW Cloudflare is the front (the origin gate
    # is configured). Hitting the origin directly, a client can forge CF-Connecting-IP / XFF to evade
    # per-IP throttling (#98), so without the gate we key on the unspoofable socket peer.
    from glitch_signal.config import settings

    if settings().origin_shared_secret:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                return parts[-1]
    client = getattr(request, "client", None)
    return client.host if client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP + constant-keyed global speed bump. `/healthz` is exempt (platform probes).

    `shared=True` (config `RATE_LIMIT_SHARED`) backs the counters with Postgres so the limit is
    enforced fleet-wide instead of per-worker (#98). Default is the in-process limiter — the shared
    backend adds a DB round-trip per request, and this is a backstop with Cloudflare WAF as the real
    control, so operators opt in per-env. Both backends fail open.
    """

    def __init__(self, app: Any, *, per_ip: int, window_s: int, global_limit: int,
                 shared: bool = False) -> None:
        super().__init__(app)
        self._shared = shared
        if shared:
            from glitch_signal.middleware.shared_state import SharedWindowLimiter
            self._ip = SharedWindowLimiter(per_ip, window_s)
            self._global = SharedWindowLimiter(global_limit, window_s)
        else:
            self._ip = SlidingWindowLimiter(per_ip, window_s)
            self._global = SlidingWindowLimiter(global_limit, window_s)

    async def _check(self, ip: str) -> tuple[bool, int]:
        """Return (allowed, retry_after). Unifies the sync in-process and async shared backends."""
        if self._shared:
            ip_ok, ip_retry = await self._ip.check(f"ip:{ip}")
            g_ok, g_retry = await self._global.check("all")
            return (ip_ok and g_ok), max(ip_retry, g_retry, 1)
        if not self._ip.allow(ip) or not self._global.allow("all"):
            return False, max(self._ip.retry_after(ip), self._global.retry_after("all"), 1)
        return True, 0

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        path = request.url.path
        # /healthz = platform probes; /webhooks/* + /resend/webhook = provider callbacks
        # (signature-verified, retried on failure — must not be rate-limited).
        if path == "/healthz" or path.startswith("/webhooks") or path == "/resend/webhook":
            return await call_next(request)
        allowed, retry = await self._check(client_ip(request))
        if not allowed:
            return Response(
                content=json.dumps({"detail": "Too many requests."}),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
