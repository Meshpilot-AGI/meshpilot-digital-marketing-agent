"""Collect what published posts actually achieved — the learning loop's sensor.

Before this, `curator.py` distilled lessons only from the agent's own account of what it did, so a
"durable lesson" could be learned from a post that flopped. Readings are taken at fixed age buckets
(not continuously) because engagement accrues over days — "this post at 24h" vs "that post at 24h" is
the only comparable quantity; readings spaced by sweep timing are not.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from glitch_signal.platforms.insights import MEASURABLE

log = structlog.get_logger(__name__)

# (bucket, min age, max age). The upper bound stops an old backlog being read at the wrong age and
# recorded as if it were a fresh 1h reading.
BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("1h", 3600, 6 * 3600),
    ("24h", 24 * 3600, 48 * 3600),
    ("7d", 7 * 86400, 10 * 86400),
)
BATCH_LIMIT = 25
_running = asyncio.Lock()


def _still_in_window(measured_from: Any, lo: int, hi: int) -> bool:
    """True if `measured_from` is still within [lo, hi) as of right now.

    `posts_due_for_metrics` bounds age as of the SELECT, but the round trip to `fetch()` (plus
    everything ahead of this row in a rate-limited batch) can push the real age past the window by
    write time. The `unique (post_id, age_bucket)` constraint makes the first write permanent, so a
    late write would lock in a value the bucket doesn't actually represent.
    """
    if measured_from is None:
        return True                     # no timestamp to check against — don't block on it
    if measured_from.tzinfo is None:
        measured_from = measured_from.replace(tzinfo=UTC)
    age_s = (datetime.now(UTC) - measured_from).total_seconds()
    return lo <= age_s < hi


async def collect(*, store_mod: Any = None, fetch: Any = None,
                  engine: Any = None) -> dict[str, int]:
    """Take any readings that are due. Never raises — this runs from the cron tick."""
    from glitch_signal.agent.social import store as _store
    store_mod = store_mod or _store
    if fetch is None:
        from glitch_signal.platforms.insights import fetch as fetch  # noqa: PLW0127

    counts = {"read": 0, "unmeasured": 0}
    if _running.locked():
        log.debug("social.outcomes_skipped_overlap")
        return counts
    async with _running:
        for bucket, lo, hi in BUCKETS:
            try:
                due = await store_mod.posts_due_for_metrics(
                    min_age_s=lo, max_age_s=hi, bucket=bucket, platforms=MEASURABLE,
                    limit=BATCH_LIMIT, engine=engine)
            except Exception as exc:  # noqa: BLE001
                log.warning("social.outcomes_query_failed", bucket=bucket, error=str(exc)[:200])
                continue
            for row in due:
                m = await fetch(row["platform"], str(row["platform_post_id"]),
                                brand_id=row.get("brand_id"))
                if m is None:
                    # Not recorded as zeros — indistinguishable from genuine silence, corrupts comparisons.
                    counts["unmeasured"] += 1
                    continue
                if not _still_in_window(row.get("measured_from"), lo, hi):
                    # Skip rather than record a stale reading; next sweep picks it up under the
                    # bucket that now actually matches its age.
                    log.warning("social.outcomes_stale_reading_skipped", post_id=str(row["id"]),
                               bucket=bucket)
                    continue
                try:
                    await store_mod.record_metrics(str(row["id"]), row["platform"], bucket, m,
                                                   engine=engine)
                    counts["read"] += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("social.outcomes_write_failed", post_id=str(row["id"]),
                                error=str(exc)[:200])
    if counts["read"] or counts["unmeasured"]:
        log.info("social.outcomes", **counts)
    return counts
