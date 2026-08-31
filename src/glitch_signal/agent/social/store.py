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
                       verdict: str, *, engine: Any = None) -> bool:
    """Durable OUTBOX: reserve the per-platform row (status='pending') BEFORE the external publish.

    Returns True if newly inserted (caller should proceed to publish); False if a row already
    exists for (campaign_id, platform) — an already-attempted/uncertain request that must NOT be
    blindly republished (idempotency).
    """
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(
            text("INSERT INTO social_post (campaign_id, platform, media_kind, caption, verdict, "
                 "status) VALUES (CAST(:cid AS uuid), :platform, :media_kind, :caption, :verdict, "
                 "'pending') ON CONFLICT (campaign_id, platform) DO NOTHING RETURNING id"),
            {"cid": campaign_id, "platform": platform, "media_kind": media_kind,
             "caption": caption, "verdict": verdict})).first()
    return row is not None


async def mark_result(campaign_id: str, platform: str, status: str, *, platform_post_id: str | None,
                      post_url: str | None, error: str | None, engine: Any = None) -> None:
    """Update the outbox row AFTER the publish call resolves (terminal or pending-terminal)."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_post SET status = :s, platform_post_id = :ppid, post_url = :url, "
                 "error = :err WHERE campaign_id = CAST(:cid AS uuid) AND platform = :p"),
            {"s": status, "ppid": platform_post_id, "url": post_url, "err": error,
             "cid": campaign_id, "p": platform})


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
