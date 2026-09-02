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


async def recent_choices(brand_id: str, *, limit: int = 40, engine: Any = None) -> list[dict]:
    """The choices behind recent campaigns — the matrix's sampling history. Recent, not all-time, so
    the matrix can re-explore after a strategy change instead of letting early posts pin it forever."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            rows = (await conn.execute(
                text("SELECT choices FROM social_campaign WHERE brand_id = :brand "
                     "ORDER BY created_at DESC LIMIT :k"),
                {"brand": brand_id, "k": limit})).fetchall()
        out = []
        for r in rows:
            v = r[0]
            if isinstance(v, str):
                import json
                v = json.loads(v)
            if isinstance(v, dict):
                out.append(v)
        return out
    except Exception as exc:  # noqa: BLE001 — no history just means "explore from the start"
        import structlog
        structlog.get_logger(__name__).warning("social.recent_choices_failed",
                                               brand_id=brand_id, error=str(exc)[:200])
        return []


async def reserve_campaign(brand_id: str, idea: Idea, *, choices: dict | None = None,
                           engine: Any = None) -> str | None:
    """Atomically reserve a campaign row before any paid work — the DB is the dedup authority.

    `ON CONFLICT (brand_id, dedup_key) DO NOTHING` (unique index from 20260831010000) means two
    concurrent runs of the same idea can never both reserve it. Media URLs come later via
    `finalize_campaign`.
    """
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(
            text("INSERT INTO social_campaign (brand_id, dedup_key, idea, status, choices) "
                 "VALUES (:brand, :dedup_key, CAST(:idea AS jsonb), 'reserved', "
                 "CAST(:choices AS jsonb)) "
                 "ON CONFLICT (brand_id, dedup_key) DO NOTHING RETURNING id"),
            {"brand": brand_id, "dedup_key": idea.dedup_key,
             "idea": json.dumps(asdict(idea)),
             "choices": json.dumps(choices or {})})).first()
    return str(row[0]) if row else None


async def mark_pending(campaign_id: str, platform: str, media_kind: str, caption: str,
                       verdict: str, *, idem_key: str | None = None, engine: Any = None) -> bool:
    """Durable outbox: reserve the per-platform row (status='pending') before the external publish.

    Returns True if newly inserted (proceed to publish); False if a row already exists for
    (campaign_id, platform) — an already-attempted/uncertain request that must not be republished.

    `idem_key` is persisted before the provider call and echoed to it in the post `source` field, so
    a submission whose response is lost can still be tied back to this row.
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
    """Update the outbox row after the publish call resolves. Stamps `submitted_at` whenever a
    provider id came back — that's what makes the row eligible for the reconciler."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_post SET status = :s, platform_post_id = :ppid, post_url = :url, "
                 # CAST is load-bearing: asyncpg can't infer a type from bare `:ppid IS NULL` and
                 # raises AmbiguousParameterError. FakeEngine in unit tests doesn't type-check
                 # params, so this passed every test and failed on the first real publish.
                 "error = :err, submitted_at = CASE WHEN CAST(:ppid AS text) IS NULL "
                 "THEN submitted_at ELSE COALESCE(submitted_at, now()) END "
                 "WHERE campaign_id = CAST(:cid AS uuid) AND platform = :p"),
            {"s": status, "ppid": platform_post_id, "url": post_url, "err": error,
             "cid": campaign_id, "p": platform})


async def pending_for_reconcile(*, older_than_s: int, limit: int = 25, max_attempts: int = 20,
                                engine: Any = None) -> list[dict]:
    """Outbox rows still 'pending' past the settle window — the reconciler's working set.

    Only rows with a provider id are returned (nothing to poll without one); a row past
    `max_attempts` is left alone so an unresolvable post can't spin the sweep forever.
    """
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT p.id, p.campaign_id, p.platform, p.platform_post_id, "
                 "       p.reconcile_attempts, c.brand_id "
                 "FROM social_post p JOIN social_campaign c ON c.id = p.campaign_id "
                 "WHERE p.status = 'pending' AND p.platform_post_id IS NOT NULL "
                 # Age from provider acceptance (submitted_at), not outbox reservation (created_at)
                 # which happens strictly earlier — else rows go eligible before the settle window.
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
    """Update only the aggregate status, leaving cost and media URLs untouched — `finalize_campaign`
    would clobber recorded spend, and reconciliation happens long after the run."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_campaign SET status = :s WHERE id = CAST(:cid AS uuid)"),
            {"s": status, "cid": campaign_id})


async def stranded_pending(*, older_than_s: int, limit: int = 25,
                           engine: Any = None) -> list[dict]:
    """Pending rows with no provider id — publish succeeded but persisting the result exhausted its
    retries. `idem_key` (sent to Buffer in the post `source` field) is the only handle an operator
    has to find the real post; surfacing these is the recovery path.
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

    Bucketed, not polled continuously — engagement needs to be read at comparable ages, and the
    `unique (post_id, age_bucket)` constraint plus this NOT EXISTS makes each reading exactly-once.

    Returns `measured_from` alongside each row so the caller can re-check freshness right before
    writing: this SELECT bounds age as of query time, but a slow fetch can let real age drift past
    the window before `record_metrics` runs, and the unique constraint would lock that value in.
    """
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT p.id, p.platform, p.platform_post_id, p.media_kind, c.brand_id, "
                 "       c.idea, c.id AS campaign_id, "
                 "       coalesce(p.submitted_at, p.created_at) AS measured_from "
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
    """Persist one reading. Absent metrics stay NULL, never coerced to 0 — a fabricated zero would
    make "nobody engaged" indistinguishable from "we could not measure"."""
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
