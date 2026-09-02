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
