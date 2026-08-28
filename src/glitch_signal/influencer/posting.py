"""Posting step for the influencer pipeline.

Publishes a generated asset (still or video) for a content-plan row via
Upload-Post — the same audited partner the rest of the agent uses — then
returns the vendor request id so the row can be finalized when the
`upload_completed` webhook (or poll fallback) lands.

This is intentionally a thin, influencer-native wrapper rather than the
ORM-bound platforms.upload_post.publish(): the plan row already carries
the caption + asset URL, so we don't need ContentScript / ScheduledPost.
We honour the same DISPATCH_MODE=dry_run short-circuit and per-brand
Upload-Post profile config.

Per-brand config (brand/<brand>.json):
  platforms.upload_post_<target>.{enabled, user}
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog

from glitch_signal.config import brand_config, settings

log = structlog.get_logger(__name__)

# persona/plan platform -> Upload-Post platform-key suffix
_PLATFORM_KEY = {
    "instagram": "upload_post_instagram",
    "tiktok": "upload_post_tiktok",
    "youtube": "upload_post_youtube",
    "youtube_shorts": "upload_post_youtube",
}
_VIDEO_KINDS = {"video"}


@dataclass(slots=True)
class PostResult:
    request_id: str
    platform: str
    dry_run: bool
    pending: bool = True   # finalized by webhook/poll


def _profile_user(brand_id: str, platform_key: str) -> str | None:
    try:
        cfg = brand_config(brand_id)
    except Exception:  # noqa: BLE001
        return None
    block = ((cfg.get("platforms") or {}).get(platform_key)) or {}
    if not block.get("enabled"):
        return None
    return block.get("user")


def post_asset(
    *,
    brand_id: str,
    platform: str,
    asset_url: str,
    caption: str,
    kind: str = "video",
    title: str | None = None,
) -> PostResult:
    """Publish one asset. Synchronous (Upload-Post SDK is sync)."""
    s = settings()
    platform = (platform or "instagram").strip().lower()
    pkey = _PLATFORM_KEY.get(platform, f"upload_post_{platform}")
    target = pkey.removeprefix("upload_post_")

    if s.is_dry_run:
        rid = f"uploadpost-dry-{uuid.uuid4().hex[:10]}"
        log.info("influencer.post.dry_run", brand=brand_id, platform=target, asset=asset_url[:80])
        return PostResult(request_id=rid, platform=target, dry_run=True)

    if not s.upload_post_api_key:
        raise RuntimeError("UPLOAD_POST_API_KEY is not set")
    user = _profile_user(brand_id, pkey)
    if not user:
        raise RuntimeError(
            f"no enabled Upload-Post profile for {brand_id}/{pkey} — "
            f"set platforms.{pkey}.{{enabled,user}} in the brand config"
        )

    import upload_post

    client = upload_post.UploadPostClient(api_key=s.upload_post_api_key)
    title_is_caption = target in ("tiktok", "instagram", "x", "threads", "bluesky")
    if kind in _VIDEO_KINDS:
        kwargs = dict(video_path=asset_url, user=user, platforms=[target])
        if title_is_caption:
            kwargs["title"] = caption
        else:
            kwargs["title"] = title or caption[:90]
            kwargs["description"] = caption
        resp = client.upload_video(**kwargs)
    else:
        kwargs = dict(photos=[asset_url], user=user, platforms=[target])
        kwargs["title" if title_is_caption else "caption"] = caption
        resp = client.upload_photos(**kwargs)

    if not resp.get("success", True):
        raise RuntimeError(f"Upload-Post failed: {resp}")
    rid = (
        resp.get("request_id")
        or (resp.get("results", {}) or {}).get("request_id")
        or str(uuid.uuid4())
    )
    log.info("influencer.post.submitted", brand=brand_id, platform=target, user=user, request_id=rid)
    return PostResult(request_id=rid, platform=target, dry_run=False)
