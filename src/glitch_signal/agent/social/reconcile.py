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

import asyncio
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Buffer needs a moment to actually push the post; polling instantly just burns quota on "sending".
SETTLE_WINDOW_S = 180
BATCH_LIMIT = 25
# A row whose provider id was never persisted has nothing to poll. After this long it is surfaced as
# needing an operator, keyed by the correlation tag we sent Buffer in the post `source` field.
STRANDED_WINDOW_S = 6 * 3600
# One sweep at a time. The cron tick is 20s but a batch can make 25 sequential vendor polls of up to
# 15s each, so without this the sweeps overlap: `pending_for_reconcile` takes no lock, so concurrent
# runs select the SAME rows, duplicate vendor requests, and burn the attempt budget many times faster
# than intended.
_running = asyncio.Lock()
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

    counts = {"checked": 0, "posted": 0, "failed": 0, "in_flight": 0, "stranded": 0}
    if _running.locked():
        # A previous sweep is still working the same unlocked rows. Skipping is correct, not a
        # missed beat: the next tick picks up whatever remains.
        log.debug("social.reconcile_skipped_overlap")
        return counts
    async with _running:
        return await _sweep(store_mod, poll, engine, counts)


async def _sweep(store_mod: Any, poll: Any, engine: Any, counts: dict[str, int]) -> dict[str, int]:
    from glitch_signal.platforms.buffer import BufferPostFailed

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
            # None means "still in flight, try again next tick".
            ppid, url = await poll(str(row["platform_post_id"]), None, row.get("brand_id"))
        except BufferPostFailed as exc:
            # TERMINAL. Treating this as retryable was the bug: the row burned its whole attempt
            # budget and then sat pending forever, with the failure never recorded.
            await _resolve(store_mod, post_id, "failed", error=str(exc)[:200], engine=engine)
            await _rollup(store_mod, row.get("campaign_id"), engine)
            counts["failed"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 — transport / GraphQL / rate limit → retry
            log.warning("social.reconcile_poll_failed", post_id=post_id,
                        platform=row.get("platform"), error=str(exc)[:200])
            await _bump(store_mod, post_id, engine)
            continue

        if ppid:
            await _resolve(store_mod, post_id, "posted", url=url, engine=engine)
            await _rollup(store_mod, row.get("campaign_id"), engine)
            counts["posted"] += 1
        else:
            await _bump(store_mod, post_id, engine)
            counts["in_flight"] += 1

    counts["stranded"] += await _surface_stranded(store_mod, engine)
    if counts["checked"] or counts["stranded"]:
        log.info("social.reconcile", **counts)
    return counts


async def _rollup(store_mod: Any, campaign_id: Any, engine: Any) -> None:
    """Recompute the PARENT campaign's aggregate status after a post reaches a terminal state.

    `run_campaign` finalizes the campaign from the fan-out result, when accepted Buffer submissions
    are deliberately still `pending`. Reconciliation is the later terminal transition — without this
    the posts settle but the campaign is stuck reading `pending`/`partial` forever.
    """
    if not campaign_id:
        return
    try:
        from glitch_signal.agent.social.spec import derive_status

        statuses = await store_mod.campaign_post_statuses(str(campaign_id), engine=engine)
        if not statuses or any(s == "pending" for s in statuses):
            return                      # still in flight — roll up only once everything is terminal
        await store_mod.set_campaign_status(
            str(campaign_id),
            derive_status([_S(s) for s in statuses]), engine=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.reconcile_rollup_failed", campaign_id=str(campaign_id),
                    error=str(exc)[:200])


class _S:
    """Minimal shim so `derive_status` (which reads `.status`) can consume bare status strings."""

    __slots__ = ("status",)

    def __init__(self, status: str) -> None:
        self.status = status


async def _surface_stranded(store_mod: Any, engine: Any) -> int:
    """Flag pending rows with no provider id so they stop being invisible.

    These are publishes whose result write exhausted its retries. There is nothing to poll, so the
    reconciler can never settle them on its own; the correlation key we sent Buffer in the post
    `source` field is the handle an operator can search on.
    """
    try:
        rows = await store_mod.stranded_pending(older_than_s=STRANDED_WINDOW_S, engine=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.reconcile_stranded_query_failed", error=str(exc)[:200])
        return 0
    for r in rows:
        log.error("social.post_stranded", post_id=str(r["id"]), platform=r.get("platform"),
                  idem_key=r.get("idem_key"), brand_id=r.get("brand_id"),
                  hint="find the Buffer post by this idem_key in its `source` field")
        await _resolve(store_mod, str(r["id"]), "unresolved",
                       error=f"provider id never persisted; correlate via source={r.get('idem_key')}",
                       engine=engine)
    return len(rows)


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
