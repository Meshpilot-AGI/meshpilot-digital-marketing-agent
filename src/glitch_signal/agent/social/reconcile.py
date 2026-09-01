"""Reconcile asynchronous social publishes to a terminal state — SOCIAL outbox sweep.

Buffer accepts a post and returns "sending", which is NOT delivery. `publish.publish_one` records
that honestly as `social_post.status='pending'` with the Buffer post id — but nothing then moved
those rows forward, so every Buffer submission stayed `pending` forever and `derive_status` could
never settle a campaign.

The scheduler's `_reconcile_awaiting_webhook` does the equivalent job for the OTHER queue model
(`ScheduledPost` rows keyed on `vendor_request_id`); it does not know about `social_post`. This is
the same idea applied to the social outbox, sharing the same vendor poll
(`platforms.buffer.poll_status_for_post`).

Meta platforms (facebook/instagram) return a real post id synchronously and are already terminal at
publish time, so they never appear in this sweep.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Buffer needs a moment to actually push the post; polling instantly just burns quota on "sending".
SETTLE_WINDOW_S = 180
BATCH_LIMIT = 25
# Bound the retries per row. Roughly a day of sweeps at the default cadence — after that a stuck row
# is a real anomaly to look at, not something to keep polling.
MAX_ATTEMPTS = 20


async def reconcile_pending(*, store_mod: Any = None, poll: Any = None,
                            engine: Any = None) -> dict[str, int]:
    """Poll each settled-but-pending outbox row once and move it to a terminal state.

    Returns a small counter dict: {"checked", "posted", "failed", "in_flight"}.
    Never raises — a vendor or DB error on one row must not stop the rest of the sweep, and this
    runs from the cron tick where an exception would be invisible.
    """
    from glitch_signal.agent.social import store as _store
    store_mod = store_mod or _store
    if poll is None:
        from glitch_signal.platforms.buffer import poll_status_for_post as poll

    counts = {"checked": 0, "posted": 0, "failed": 0, "in_flight": 0}
    try:
        rows = await store_mod.pending_for_reconcile(
            older_than_s=SETTLE_WINDOW_S, limit=BATCH_LIMIT, max_attempts=MAX_ATTEMPTS,
            engine=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.reconcile_query_failed", error=str(exc)[:200])
        return counts

    for row in rows:
        counts["checked"] += 1
        post_id = str(row["id"])
        try:
            # A None return means "still in flight, try again next tick"; a RuntimeError means
            # Buffer rejected the post outright.
            ppid, url = await poll(str(row["platform_post_id"]), None, row.get("brand_id"))
        except Exception as exc:  # noqa: BLE001
            log.warning("social.reconcile_poll_failed", post_id=post_id,
                        platform=row.get("platform"), error=str(exc)[:200])
            await _bump(store_mod, post_id, engine)
            continue

        if ppid:
            await _resolve(store_mod, post_id, "posted", url=url, engine=engine)
            counts["posted"] += 1
        else:
            await _bump(store_mod, post_id, engine)
            counts["in_flight"] += 1

    if counts["checked"]:
        log.info("social.reconcile", **counts)
    return counts


async def _resolve(store_mod: Any, post_id: str, status: str, *, url: str | None = None,
                   error: str | None = None, engine: Any = None) -> None:
    try:
        await store_mod.resolve_pending(post_id, status, post_url=url, error=error, engine=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.reconcile_resolve_failed", post_id=post_id, error=str(exc)[:200])


async def _bump(store_mod: Any, post_id: str, engine: Any) -> None:
    try:
        await store_mod.bump_reconcile_attempt(post_id, engine=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.reconcile_bump_failed", post_id=post_id, error=str(exc)[:200])
