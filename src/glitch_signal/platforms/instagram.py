"""Instagram publisher (Meta Graph API) — container → publish flow.

Publishes to a brand's Instagram Business/Creator account (linked to its FB Page).
All credentials resolve PER-BRAND via `config.brand_env` — there are no global keys:

    <PREFIX>_META_IG_USER_ID     the IG Business account id (publish target)
    <PREFIX>_META_PAGE_ID        the linked FB Page (to mint the page access token)
    <PREFIX>_SYSTEM_USER_TOKEN   a Meta system-user token with publish access

Flow (Graph API):
    image: POST /{ig_user}/media {image_url, caption}                     -> creation_id
    reel : POST /{ig_user}/media {media_type: REELS, video_url, caption}  -> creation_id
           then poll GET /{creation_id}?fields=status_code until FINISHED
    publish: POST /{ig_user}/media_publish {creation_id}                  -> media_id

Meta requires the media to be a PUBLIC URL — STORAGE-1's Supabase public URLs
satisfy this. This replaces the old Upload-Post-based IG path (VENDOR-1).
"""
from __future__ import annotations

import asyncio

import httpx
import structlog

from glitch_signal.config import brand_env, settings
from glitch_signal.platforms.facebook import _fetch_page_token  # reuse the token exchange

log = structlog.get_logger(__name__)

_GRAPH = "https://graph.facebook.com"


def _base(node_id: str) -> str:
    return f"{_GRAPH}/{settings().meta_graph_api_version}/{node_id}"


def resolve_instagram_creds(brand_id: str | None = None) -> tuple[str, str, str]:
    """(ig_user_id, page_id, system_user_token) for the brand. Raises if unset."""
    ig_user_id = brand_env("META_IG_USER_ID", brand_id)
    page_id = brand_env("META_PAGE_ID", brand_id)
    system_user_token = brand_env("SYSTEM_USER_TOKEN", brand_id)
    if not ig_user_id:
        raise RuntimeError("instagram: <PREFIX>_META_IG_USER_ID is not set for this brand.")
    if not page_id:
        raise RuntimeError("instagram: <PREFIX>_META_PAGE_ID is not set for this brand.")
    if not system_user_token:
        raise RuntimeError("instagram: <PREFIX>_SYSTEM_USER_TOKEN is not set for this brand.")
    return ig_user_id, page_id, system_user_token


def build_container(
    ig_user_id: str,
    page_token: str,
    *,
    caption: str | None = None,
    image_url: str | None = None,
    video_url: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Pure: (url, form_data) for the media-container create call.

    Image wins over video if both are passed (callers normally pass one).
    """
    if image_url:
        data = {"image_url": image_url, "access_token": page_token}
    elif video_url:
        data = {"media_type": "REELS", "video_url": video_url, "access_token": page_token}
    else:
        raise ValueError("instagram: need image_url or video_url")
    if caption:
        data["caption"] = caption
    return f"{_base(ig_user_id)}/media", data


async def _wait_container(
    creation_id: str, page_token: str, *, timeout_s: int = 240, interval_s: int = 4
) -> None:
    """Poll a video/reel container until Meta finishes ingesting it."""
    async with httpx.AsyncClient(timeout=30) as client:
        waited = 0
        while waited < timeout_s:
            r = await client.get(
                _base(creation_id),
                params={"fields": "status_code"},
                headers={"Authorization": f"Bearer {page_token}"},
            )
            code = (r.json() or {}).get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"instagram: container {creation_id} status={code}")
            await asyncio.sleep(interval_s)
            waited += interval_s
    raise RuntimeError(f"instagram: container {creation_id} not FINISHED in {timeout_s}s")


async def publish_instagram(
    *,
    brand_id: str | None = None,
    caption: str | None = None,
    image_url: str | None = None,
    video_url: str | None = None,
) -> tuple[str, str]:
    """Publish an image or reel to the brand's IG account. Returns (media_id, permalink)."""
    if settings().is_dry_run:
        log.info("instagram.publish.dry_run", brand_id=brand_id, is_video=bool(video_url))
        return "ig-dry-run", ""
    ig_user_id, page_id, system_user_token = resolve_instagram_creds(brand_id)
    page_token = await _fetch_page_token(page_id, system_user_token)
    url, data = build_container(
        ig_user_id, page_token, caption=caption, image_url=image_url, video_url=video_url
    )
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, data=data)
        if r.status_code >= 400:
            log.error("instagram.container_failed", status=r.status_code, body=r.text[:500])
            r.raise_for_status()
        creation_id = (r.json() or {}).get("id")
        if not creation_id:
            raise RuntimeError(f"instagram: no container id returned: {r.text[:200]}")

        if video_url:  # reels ingest asynchronously — wait before publishing
            await _wait_container(creation_id, page_token)

        pub = await client.post(
            f"{_base(ig_user_id)}/media_publish",
            data={"creation_id": creation_id, "access_token": page_token},
        )
        if pub.status_code >= 400:
            log.error("instagram.publish_failed", status=pub.status_code, body=pub.text[:500])
            pub.raise_for_status()
        media_id = (pub.json() or {}).get("id", "")

        permalink = ""
        try:
            pr = await client.get(
                _base(media_id),
                params={"fields": "permalink"},
                headers={"Authorization": f"Bearer {page_token}"},
            )
            permalink = (pr.json() or {}).get("permalink", "")
        except Exception:  # noqa: BLE001 — permalink is best-effort
            pass

    log.info("instagram.published", ig_user_id=ig_user_id, media_id=media_id)
    return media_id, permalink
