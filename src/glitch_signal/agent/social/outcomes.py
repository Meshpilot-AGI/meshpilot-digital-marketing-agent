"""Collect what published posts actually achieved — the learning loop's sensor.

Before this, `curator.py` distilled lessons from `kind='episode'` memories: the agent's own account
of what it did. Nothing read back what any post achieved, so a "durable lesson" could be learned
from a post that flopped. Measurement has to exist before revision means anything.

Readings are taken at fixed AGE BUCKETS rather than continuously. Engagement accrues over days, so
the comparable quantity is "this post at 24h" against "that post at 24h" — a stream of readings
whose spacing depends on sweep timing is not comparable, and re-reading the same post hourly mostly
buys API quota spend and noise.
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

    `posts_due_for_metrics` bounds age as of the SELECT — but the network round trip to `fetch()`
    (and, in a large or rate-limited batch, everything ahead of a given row) takes real time, so by
    the time a row is about to be written its true age can have drifted past the bucket's window. A
    bucket must only fill from a reading actually taken within its window: the `unique
    (post_id, age_bucket)` constraint makes the first write permanent, so a late write would lock in
    a value that does not represent what the bucket claims to measure.
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
                    # NOT MEASURED — deliberately not recorded as zeros, which would be
                    # indistinguishable from genuine silence and would corrupt every comparison.
                    counts["unmeasured"] += 1
                    continue
                if not _still_in_window(row.get("measured_from"), lo, hi):
                    # The read came back too late for this bucket: the post's real age drifted past
                    # the window between the SELECT and this write. Skip rather than record — the
                    # unique constraint would otherwise lock in a reading that isn't comparable to
                    # every other post's "1h"/"24h"/"7d" value. Leaving it unwritten means the next
                    # sweep will pick it up under whichever bucket now actually matches its age.
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
