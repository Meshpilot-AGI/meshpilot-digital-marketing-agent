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


async def create_campaign(brand_id: str, idea: Idea, *, image_url: str | None,
                          video_url: str | None, engine: Any = None) -> str:
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(
            text("INSERT INTO social_campaign (brand_id, dedup_key, idea, image_url, video_url) "
                 "VALUES (:brand, :dedup_key, CAST(:idea AS jsonb), :image_url, :video_url) "
                 "RETURNING id"),
            {"brand": brand_id, "dedup_key": idea.dedup_key, "idea": json.dumps(asdict(idea)),
             "image_url": image_url, "video_url": video_url})).first()
    return str(row[0])


async def already_posted(campaign_id: str, platform: str, *, engine: Any = None) -> bool:
    eng = engine or _engine()
    async with eng.connect() as conn:
        row = (await conn.execute(
            text("SELECT 1 FROM social_post WHERE campaign_id = CAST(:cid AS uuid) "
                 "AND platform = :p AND status = 'posted' LIMIT 1"),
            {"cid": campaign_id, "p": platform})).first()
    return row is not None


async def record_post(campaign_id: str, r: PlatformResult, media_kind: str, caption: str,
                      *, engine: Any = None) -> None:
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


async def finalize_campaign(campaign_id: str, status: str, cost_usd: float,
                            *, engine: Any = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_campaign SET status = :s, cost_usd = :c "
                 "WHERE id = CAST(:cid AS uuid)"),
            {"s": status, "c": cost_usd, "cid": campaign_id})
