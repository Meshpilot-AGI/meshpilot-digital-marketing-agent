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
    """Per-IP + constant-keyed global speed bump. `/healthz` is exempt (platform probes)."""

    def __init__(self, app: Any, *, per_ip: int, window_s: int, global_limit: int) -> None:
        super().__init__(app)
        self._ip = SlidingWindowLimiter(per_ip, window_s)
        self._global = SlidingWindowLimiter(global_limit, window_s)

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        path = request.url.path
        # /healthz = platform probes; /webhooks/* = provider callbacks (HMAC-verified, retried).
        if path == "/healthz" or path.startswith("/webhooks"):
            return await call_next(request)
        ip = client_ip(request)
        if not self._ip.allow(ip) or not self._global.allow("all"):
            retry = max(self._ip.retry_after(ip), self._global.retry_after("all"), 1)
            return Response(
                content=json.dumps({"detail": "Too many requests."}),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
