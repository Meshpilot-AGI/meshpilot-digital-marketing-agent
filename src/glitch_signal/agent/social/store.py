from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import text

from glitch_signal.agent.social.spec import Idea, PlatformResult
from glitch_signal.db.session import _engine


async def recent_dedup_keys(brand_id: str, *, limit: int = 20, engine: Any = None) -> set[str]:
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT dedup_key FROM social_campaign WHERE brand_id = :brand "
                 "ORDER BY created_at DESC LIMIT :k"),
            {"brand": brand_id, "k": limit})).fetchall()
    return {r._mapping["dedup_key"] if hasattr(r, "_mapping") else r[0] for r in rows}


async def reserve_campaign(brand_id: str, idea: Idea, *, engine: Any = None) -> str | None:
    """Atomically RESERVE a campaign row BEFORE any paid work — the DB is the dedup authority.

    `ON CONFLICT (brand_id, dedup_key) DO NOTHING` (unique index from 20260831010000) means two
    concurrent runs of the same idea can never both reserve it: the loser gets no row back and the
    caller cleanly skips. Media URLs are filled in later via `finalize_campaign`.
    """
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(
            text("INSERT INTO social_campaign (brand_id, dedup_key, idea, status) "
                 "VALUES (:brand, :dedup_key, CAST(:idea AS jsonb), 'reserved') "
                 "ON CONFLICT (brand_id, dedup_key) DO NOTHING RETURNING id"),
            {"brand": brand_id, "dedup_key": idea.dedup_key,
             "idea": json.dumps(asdict(idea))})).first()
    return str(row[0]) if row else None


async def mark_pending(campaign_id: str, platform: str, media_kind: str, caption: str,
                       verdict: str, *, idem_key: str | None = None, engine: Any = None) -> bool:
    """Durable OUTBOX: reserve the per-platform row (status='pending') BEFORE the external publish.

    Returns True if newly inserted (caller should proceed to publish); False if a row already
    exists for (campaign_id, platform) — an already-attempted/uncertain request that must NOT be
    blindly republished (idempotency).

    `idem_key` is the caller's pre-generated correlation key. It is persisted BEFORE the provider is
    called and echoed to the provider in the post `source` field, so a submission whose response is
    lost can still be tied back to this row.
    """
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(
            text("INSERT INTO social_post (campaign_id, platform, media_kind, caption, verdict, "
                 "status, idem_key) VALUES (CAST(:cid AS uuid), :platform, :media_kind, :caption, "
                 ":verdict, 'pending', :idem) "
                 "ON CONFLICT (campaign_id, platform) DO NOTHING RETURNING id"),
            {"cid": campaign_id, "platform": platform, "media_kind": media_kind,
             "caption": caption, "verdict": verdict, "idem": idem_key})).first()
    return row is not None


async def mark_result(campaign_id: str, platform: str, status: str, *, platform_post_id: str | None,
                      post_url: str | None, error: str | None, engine: Any = None) -> None:
    """Update the outbox row AFTER the publish call resolves (terminal or pending-terminal).

    Stamps `submitted_at` whenever a provider id came back, which is what makes the row eligible
    for the reconciler — see `reconcile.py`.
    """
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_post SET status = :s, platform_post_id = :ppid, post_url = :url, "
                 "error = :err, submitted_at = CASE WHEN :ppid IS NULL THEN submitted_at "
                 "ELSE COALESCE(submitted_at, now()) END "
                 "WHERE campaign_id = CAST(:cid AS uuid) AND platform = :p"),
            {"s": status, "ppid": platform_post_id, "url": post_url, "err": error,
             "cid": campaign_id, "p": platform})


async def pending_for_reconcile(*, older_than_s: int, limit: int = 25, max_attempts: int = 20,
                                engine: Any = None) -> list[dict]:
    """Outbox rows still 'pending' past the settle window — the reconciler's working set.

    Only rows that carry a provider id are returned: without one there is nothing to poll. A row
    that has burned through `max_attempts` is left alone so a permanently unresolvable post cannot
    spin the sweep forever.
    """
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT p.id, p.campaign_id, p.platform, p.platform_post_id, "
                 "       p.reconcile_attempts, c.brand_id "
                 "FROM social_post p JOIN social_campaign c ON c.id = p.campaign_id "
                 "WHERE p.status = 'pending' AND p.platform_post_id IS NOT NULL "
                 # Age from when the provider ACCEPTED the post, not when we reserved the outbox
                 # row: `submitted_at` is stamped with the provider id, and the settle window is
                 # about how long Buffer has had the post — reserving happens strictly earlier, so
                 # created_at makes rows eligible before the vendor has had the full window.
                 "  AND coalesce(p.submitted_at, p.created_at) <= now() - make_interval(secs => :age) "
                 "  AND p.reconcile_attempts < :max_attempts "
                 "ORDER BY coalesce(p.submitted_at, p.created_at) LIMIT :k"),
            {"age": older_than_s, "max_attempts": max_attempts, "k": limit})).mappings().all()
    return [dict(r) for r in rows]


async def resolve_pending(post_id: str, status: str, *, post_url: str | None = None,
                          error: str | None = None, engine: Any = None) -> None:
    """Move one reconciled outbox row to its terminal state (by row id)."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_post SET status = :s, "
                 "post_url = COALESCE(:url, post_url), error = COALESCE(:err, error) "
                 "WHERE id = CAST(:id AS uuid)"),
            {"s": status, "url": post_url, "err": error, "id": post_id})


async def bump_reconcile_attempt(post_id: str, *, engine: Any = None) -> None:
    """Count one poll against a still-in-flight row so retries stay bounded."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_post SET reconcile_attempts = reconcile_attempts + 1 "
                 "WHERE id = CAST(:id AS uuid)"),
            {"id": post_id})


async def record_post(campaign_id: str, r: PlatformResult, media_kind: str, caption: str,
                      *, engine: Any = None) -> None:
    """Insert a TERMINAL row in one shot (used for held/escalate — no external side effect)."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("INSERT INTO social_post (campaign_id, platform, media_kind, caption, verdict, "
                 "status, platform_post_id, post_url, error) VALUES (CAST(:cid AS uuid), :platform, "
                 ":media_kind, :caption, :verdict, :status, :ppid, :url, :error) "
                 "ON CONFLICT (campaign_id, platform) DO NOTHING"),
            {"cid": campaign_id, "platform": r.platform, "media_kind": media_kind,
             "caption": caption, "verdict": r.verdict, "status": r.status,
             "ppid": r.platform_post_id, "url": r.post_url, "error": r.error})


async def finalize_campaign(campaign_id: str, status: str, cost_usd: float, *,
                            image_url: str | None = None, video_url: str | None = None,
                            failure_reason: str | None = None, engine: Any = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_campaign SET status = :s, cost_usd = :c, "
                 "image_url = COALESCE(:img, image_url), video_url = COALESCE(:vid, video_url), "
                 "failure_reason = COALESCE(:reason, failure_reason) "
                 "WHERE id = CAST(:cid AS uuid)"),
            {"s": status, "c": cost_usd, "img": image_url, "vid": video_url,
             "reason": failure_reason, "cid": campaign_id})


async def campaign_post_statuses(campaign_id: str, *, engine: Any = None) -> list[str]:
    """Every post status for a campaign — the input to recomputing its aggregate status."""
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT status FROM social_post WHERE campaign_id = CAST(:cid AS uuid)"),
            {"cid": campaign_id})).fetchall()
    return [r[0] for r in rows]


async def set_campaign_status(campaign_id: str, status: str, *, engine: Any = None) -> None:
    """Update ONLY the aggregate status, leaving cost and media URLs untouched.

    `finalize_campaign` is the end-of-run write and would clobber the recorded spend with whatever
    the caller passed; reconciliation happens long after the run, so it needs a narrower update.
    """
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_campaign SET status = :s WHERE id = CAST(:cid AS uuid)"),
            {"s": status, "cid": campaign_id})


async def stranded_pending(*, older_than_s: int, limit: int = 25,
                           engine: Any = None) -> list[dict]:
    """Pending rows that have NO provider id — nothing to poll, so the reconciler cannot settle them.

    These are the rows where the publish call succeeded but persisting its result exhausted its
    retries. `idem_key` is the only handle: it was sent to Buffer in the post `source` field, so an
    operator can find the real post by that tag. Surfacing them is the recovery path — silently
    leaving them pending forever is what the outbox was built to avoid.
    """
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT p.id, p.campaign_id, p.platform, p.idem_key, c.brand_id "
                 "FROM social_post p JOIN social_campaign c ON c.id = p.campaign_id "
                 "WHERE p.status = 'pending' AND p.platform_post_id IS NULL "
                 "  AND p.created_at <= now() - make_interval(secs => :age) "
                 "ORDER BY p.created_at LIMIT :k"),
            {"age": older_than_s, "k": limit})).mappings().all()
    return [dict(r) for r in rows]


# ── outcome ingestion ───────────────────────────────────────────────────────────────────────────

async def posts_due_for_metrics(*, min_age_s: int, max_age_s: int, bucket: str,
                                platforms: tuple[str, ...], limit: int = 25,
                                engine: Any = None) -> list[dict]:
    """Delivered posts old enough for this reading, that have not had it yet.

    Bucketed rather than polled continuously: engagement accrues over days, so what the loop needs
    is the same post read at comparable ages — not a stream of readings whose spacing depends on
    how often the sweep happened to run. The `unique (post_id, age_bucket)` constraint plus this
    NOT EXISTS makes each reading exactly-once and re-runnable.
    """
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT p.id, p.platform, p.platform_post_id, p.media_kind, c.brand_id, "
                 "       c.idea, c.id AS campaign_id "
                 "FROM social_post p JOIN social_campaign c ON c.id = p.campaign_id "
                 "WHERE p.status = 'posted' AND p.platform_post_id IS NOT NULL "
                 "  AND p.platform = ANY(string_to_array(:plats, ',')) "
                 "  AND coalesce(p.submitted_at, p.created_at) <= now() - make_interval(secs => :min_age) "
                 "  AND coalesce(p.submitted_at, p.created_at) >  now() - make_interval(secs => :max_age) "
                 "  AND NOT EXISTS (SELECT 1 FROM social_post_metric m "
                 "                  WHERE m.post_id = p.id AND m.age_bucket = :bucket) "
                 "ORDER BY coalesce(p.submitted_at, p.created_at) LIMIT :k"),
            {"min_age": min_age_s, "max_age": max_age_s, "bucket": bucket,
             "plats": ",".join(platforms), "k": limit})).mappings().all()
    return [dict(r) for r in rows]


async def record_metrics(post_id: str, platform: str, bucket: str, m: dict, *,
                         engine: Any = None) -> None:
    """Persist one reading. Absent metrics stay NULL — never coerced to 0.

    A fabricated zero is worse than a gap: it makes "nobody engaged" indistinguishable from "we
    could not measure", and the loop would learn from the difference.
    """
    import json as _json

    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("INSERT INTO social_post_metric (post_id, platform, age_bucket, impressions, "
                 "reach, likes, comments, shares, saves, clicks, video_views, raw) "
                 "VALUES (CAST(:pid AS uuid), :plat, :bucket, :impressions, :reach, :likes, "
                 ":comments, :shares, :saves, :clicks, :video_views, CAST(:raw AS jsonb)) "
                 "ON CONFLICT (post_id, age_bucket) DO NOTHING"),
            {"pid": post_id, "plat": platform, "bucket": bucket,
             "impressions": m.get("impressions"), "reach": m.get("reach"),
             "likes": m.get("likes"), "comments": m.get("comments"),
             "shares": m.get("shares"), "saves": m.get("saves"),
             "clicks": m.get("clicks"), "video_views": m.get("video_views"),
             "raw": _json.dumps(m.get("raw") or {})})
