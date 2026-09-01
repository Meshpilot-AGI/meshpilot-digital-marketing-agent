"""Cross-worker shared state backed by Postgres (#98).

FastAPI Cloud runs multiple workers, so an in-process set/dict can't dedup webhooks or throttle
requests across the fleet. These helpers put that state in Postgres. Both are FAIL-OPEN: a DB error
must never drop a real webhook or turn the rate-limit backstop into an outage.

The engine is injectable so this unit-tests without a real DB.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from glitch_signal.db.session import _engine

_DEDUP_INSERT = text(
    "INSERT INTO webhook_dedup (provider, event_id) VALUES (:p, :e) "
    "ON CONFLICT (provider, event_id) DO NOTHING RETURNING 1"
)
_RATE_UPSERT = text(
    "INSERT INTO rate_counters (key, window_start, window_seconds, count) VALUES (:k, :w, :ws, 1) "
    # #196: repair `window_seconds` on every conflicting write, not just the initial INSERT — a row
    # whose stored scale is wrong (e.g. NULL/unknown from the #193 backfill, or any other drift) then
    # self-heals to the caller's real value the very next time its key is touched, instead of staying
    # wrong forever because DO UPDATE only ever bumped `count`.
    "ON CONFLICT (key, window_start) DO UPDATE SET count = rate_counters.count + 1, "
    "window_seconds = excluded.window_seconds "
    "RETURNING count"
)
_CLEANUP = (
    # Each row expires on its OWN window scale (#193) — a 60s rate-limiter bucket and an 86400s
    # daily-cap bucket are NOT comparable as raw `window_start` integers, so cutoff must be computed
    # in wall-clock time per row (window_start * window_seconds), not against a single caller-supplied
    # window_s. Keep the last few windows of slack per row's own scale.
    #
    # #196: a NULL window_seconds means "unknown scale" (e.g. a row backfilled by the #193 migration
    # before its true scale could be recorded) — such a row is never pruned here; it can only be
    # reclaimed once `_RATE_UPSERT` repairs its scale on the next write, or by a separate, explicit
    # unknown-row sweep. Guessing a scale for it risks re-introducing #193's cross-scale wipe.
    text(
        "DELETE FROM rate_counters "
        "WHERE window_seconds IS NOT NULL "
        "AND window_start * window_seconds < (extract(epoch from now())::bigint - 3 * window_seconds)"
    ),
    text("DELETE FROM webhook_dedup WHERE created_at < now() - interval '30 days'"),
)


async def cleanup(*, window_s: int = 60, engine: Any | None = None) -> None:
    """Prune expired rate-counter buckets + old webhook-dedup rows (called from the scheduler). Fail-soft.

    `window_s` is accepted for backward compatibility with existing callers but is no longer used to
    compute the cutoff — each row is pruned against its own stored `window_seconds` (#193).
    """
    try:
        eng = engine or _engine()
        async with eng.begin() as conn:
            await conn.execute(_CLEANUP[0])
            await conn.execute(_CLEANUP[1])
    except Exception:  # noqa: BLE001
        pass


async def webhook_seen(provider: str, event_id: str, *, engine: Any | None = None) -> bool:
    """Record `event_id` for `provider`; return True if it was ALREADY seen (a redelivery).

    Fail-open: on any DB error return False (treat as first-seen) so a real event is never dropped.
    """
    if not event_id:
        return False
    try:
        eng = engine or _engine()
        async with eng.begin() as conn:
            row = (await conn.execute(_DEDUP_INSERT, {"p": provider, "e": event_id})).first()
        return row is None  # None ⇒ ON CONFLICT fired ⇒ already seen
    except Exception:  # noqa: BLE001 — never drop an event on a metering/DB blip
        return False


class SharedWindowLimiter:
    """Fixed-window rate limiter backed by `rate_counters` (shared across workers).

    A fixed window (one counter row per key per bucket) is a cheap, standard approximation of the
    in-process sliding window — precise enough for a backstop, one round-trip per check. Fail-open.
    """

    def __init__(self, limit: int, window_seconds: float, *, engine: Any | None = None) -> None:
        self.limit = int(limit)
        self.window = float(window_seconds)
        self._engine = engine

    async def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds). Increments the counter for the current window."""
        now = time.time()
        bucket = int(now // self.window)
        try:
            eng = self._engine or _engine()
            async with eng.begin() as conn:
                row = (
                    await conn.execute(
                        _RATE_UPSERT, {"k": key, "w": bucket, "ws": int(self.window)}
                    )
                ).first()
            count = int(row[0]) if row else 1
        except Exception:  # noqa: BLE001 — fail-open: a slow/broken DB never becomes an outage
            return True, 0
        if count > self.limit:
            retry = int((bucket + 1) * self.window - now) + 1
            return False, max(1, retry)
        return True, 0
