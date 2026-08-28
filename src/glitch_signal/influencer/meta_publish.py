"""Native Instagram publishing via the Meta Graph API (Content Publishing).

For personas whose bible carries an `accounts.meta` block (FB Page + IG
Business account under the operator's Business Manager), we post DIRECTLY
to Instagram — no third-party reseller. This is the most "real to the
platform" path and avoids Upload-Post/Zernio entirely.

Two-step IG Content Publishing:
  1. POST /{ig_user_id}/media         -> creation_id  (container)
     - image: image_url=<url>, caption=<text>
     - reel : media_type=REELS, video_url=<url>, caption=<text>
       (video containers must finish processing — poll /{id}?fields=status_code)
  2. POST /{ig_user_id}/media_publish  creation_id=<id> -> media id
  then GET /{media_id}?fields=permalink for the post URL.

Auth: a long-lived PAGE access token for the persona's FB Page, with
instagram_content_publish + instagram_basic + pages_read_engagement.
Stored per-persona in env (e.g. IG_PAGE_TOKEN_DRHARRY) so tokens never
live in the repo or the persona JSON. The app may run in dev mode — the
admin can publish to their own IG without full App Review.

DISPATCH_MODE=dry_run short-circuits without calling Graph.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from glitch_signal.config import settings

log = structlog.get_logger(__name__)

_GRAPH = "https://graph.facebook.com"
_VER = os.environ.get("META_GRAPH_API_VERSION", "v21.0")
_VIDEO_KINDS = {"video", "reel"}


class MetaPublishError(RuntimeError):
    """Non-retryable IG publish failure."""


@dataclass(slots=True)
class IgPostResult:
    media_id: str
    permalink: str | None
    dry_run: bool


def _fernet():
    from cryptography.fernet import Fernet, MultiFernet
    keys = [os.environ["MESH_PILOT_SECRETS_KEY"]]
    ring = os.environ.get("MESH_PILOT_SECRETS_KEY_RING", "")
    keys += [k.strip() for k in ring.split(",") if k.strip()]
    fers = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
    return MultiFernet(fers) if len(fers) > 1 else fers[0]


async def _fetch_token(query: str, *args) -> str | None:
    import asyncpg
    dsn = os.environ.get("POSTGRES_BRAIN_URL") or os.environ.get("HUB_DB_URL")
    if not dsn:
        return None
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(query, *args)
    finally:
        await conn.close()
    if not row or not row["encrypted_token"]:
        return None
    try:
        return _fernet().decrypt(bytes(row["encrypted_token"])).decode().strip()
    except Exception as e:  # noqa: BLE001
        log.warning("influencer.ig.token_decrypt_failed", error=str(e)[:120])
        return None


async def _brand_page_token(brand_id: str, ig_user_id: str) -> str | None:
    """A brand-specific Page token a client connected for its own asset."""
    return await _fetch_token(
        """SELECT encrypted_token FROM core.platform_accounts
           WHERE brand_id=$1 AND platform='meta'
             AND account_metadata->>'ig_user_id'=$2 AND encrypted_token IS NOT NULL
           ORDER BY connected_at DESC NULLS LAST LIMIT 1""",
        brand_id, ig_user_id,
    )


async def _owner_user_token() -> str | None:
    """The platform-owner long-lived USER token (one connection covers
    every Page/IG the owner admins). Stored under _platform/meta/owner:*."""
    return await _fetch_token(
        """SELECT encrypted_token FROM core.platform_accounts
           WHERE platform='meta' AND account_id LIKE 'owner:%'
             AND encrypted_token IS NOT NULL
           ORDER BY connected_at DESC NULLS LAST LIMIT 1""",
    )


async def _resolve_page_token(brand_id: str, page_id: str, ig_user_id: str) -> str | None:
    """Resolution order: brand-specific token → derive from platform-owner
    token → env fallback. The owner path means one Tejas connection
    publishes for ALL of his brands; a client's own token overrides."""
    tok = await _brand_page_token(brand_id, ig_user_id)
    if tok:
        return tok
    owner = await _owner_user_token()
    if owner and page_id:
        async with httpx.AsyncClient(timeout=30) as c:
            j = (await c.get(f"{_GRAPH}/{_VER}/{page_id}",
                             params={"fields": "access_token", "access_token": owner})).json()
        pt = j.get("access_token")
        if pt:
            log.info("influencer.ig.page_token_from_owner", page=page_id)
            return pt
        log.warning("influencer.ig.owner_derive_failed", error=j.get("error", {}).get("message"))
    return None


def _env_page_token(persona_id: str) -> str:
    """Fallback: per-persona Page token from env (bootstrap/dev only)."""
    key = f"IG_PAGE_TOKEN_{persona_id.upper()}"
    return (os.environ.get(key) or os.environ.get("IG_PAGE_TOKEN") or "").strip()


async def _graph_post(client: httpx.AsyncClient, path: str, data: dict[str, Any]) -> dict:
    r = await client.post(f"{_GRAPH}/{_VER}/{path}", data=data)
    j = r.json()
    if r.status_code >= 400 or "error" in j:
        raise MetaPublishError(f"{path} -> {r.status_code}: {j.get('error', j)}")
    return j


async def _graph_get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict:
    r = await client.get(f"{_GRAPH}/{_VER}/{path}", params=params)
    j = r.json()
    if r.status_code >= 400 or "error" in j:
        raise MetaPublishError(f"{path} -> {r.status_code}: {j.get('error', j)}")
    return j


async def _wait_container(client: httpx.AsyncClient, creation_id: str, token: str,
                          *, timeout_s: int = 180) -> None:
    """Poll a video/reel container until FINISHED (images are instant)."""
    waited = 0
    while waited < timeout_s:
        j = await _graph_get(client, creation_id, {"fields": "status_code", "access_token": token})
        sc = j.get("status_code")
        if sc == "FINISHED":
            return
        if sc in ("ERROR", "EXPIRED"):
            raise MetaPublishError(f"container {creation_id} {sc}")
        await asyncio.sleep(5)
        waited += 5
    raise MetaPublishError(f"container {creation_id} not finished after {timeout_s}s")


async def publish_ig(
    *,
    brand_id: str,
    persona_id: str,
    ig_user_id: str,
    asset_url: str,
    caption: str,
    kind: str = "image",
    page_id: str = "",
) -> IgPostResult:
    """Publish one asset to the persona's Instagram. Returns media id + permalink."""
    if settings().is_dry_run:
        fake = f"ig-dry-{persona_id}-{abs(hash(asset_url)) % 10**8}"
        log.info("influencer.ig.dry_run", persona=persona_id, asset=asset_url[:80])
        return IgPostResult(media_id=fake, permalink=None, dry_run=True)

    token = await _resolve_page_token(brand_id, page_id, ig_user_id) or _env_page_token(persona_id)
    if not token:
        raise MetaPublishError(
            f"no Page token for {persona_id}/{ig_user_id} — connect the account "
            "(scripts/influencer_connect_meta.py) or set env IG_PAGE_TOKEN_"
            f"{persona_id.upper()}"
        )

    async with httpx.AsyncClient(timeout=60) as client:
        # 1) create container
        if kind in _VIDEO_KINDS:
            container = await _graph_post(client, f"{ig_user_id}/media", {
                "media_type": "REELS", "video_url": asset_url,
                "caption": caption, "access_token": token,
            })
            creation_id = container["id"]
            await _wait_container(client, creation_id, token)
        else:
            container = await _graph_post(client, f"{ig_user_id}/media", {
                "image_url": asset_url, "caption": caption, "access_token": token,
            })
            creation_id = container["id"]
            await _wait_container(client, creation_id, token)

        # 2) publish
        pub = await _graph_post(client, f"{ig_user_id}/media_publish", {
            "creation_id": creation_id, "access_token": token,
        })
        media_id = pub["id"]

        # 3) permalink (best-effort)
        permalink = None
        try:
            meta = await _graph_get(client, media_id, {"fields": "permalink", "access_token": token})
            permalink = meta.get("permalink")
        except MetaPublishError:
            pass

    log.info("influencer.ig.published", persona=persona_id, media_id=media_id, kind=kind)
    return IgPostResult(media_id=media_id, permalink=permalink, dry_run=False)


@dataclass(slots=True)
class FbPostResult:
    post_id: str
    permalink: str | None
    dry_run: bool


async def publish_fb_page(
    *,
    brand_id: str,
    persona_id: str,
    page_id: str,
    ig_user_id: str = "",
    asset_url: str,
    caption: str,
    kind: str = "video",
) -> FbPostResult:
    """Publish the same asset to the persona's Facebook Page (the Page the
    IG account is attached to). Uses the same Page token as IG."""
    if settings().is_dry_run:
        fake = f"fb-dry-{persona_id}-{abs(hash(asset_url)) % 10**8}"
        log.info("influencer.fb.dry_run", persona=persona_id, asset=asset_url[:80])
        return FbPostResult(post_id=fake, permalink=None, dry_run=True)

    token = await _resolve_page_token(brand_id, page_id, ig_user_id) or _env_page_token(persona_id)
    if not token:
        raise MetaPublishError(f"no Page token for FB page {page_id}")

    async with httpx.AsyncClient(timeout=120) as client:
        if kind in _VIDEO_KINDS:
            # FB Page video: file_url is fetched server-side by Facebook.
            r = await _graph_post(client, f"{page_id}/videos", {
                "file_url": asset_url, "description": caption, "access_token": token,
            })
            post_id = r.get("id") or r.get("video_id") or ""
            permalink = f"https://www.facebook.com/{page_id}/videos/{post_id}" if post_id else None
        else:
            r = await _graph_post(client, f"{page_id}/photos", {
                "url": asset_url, "caption": caption, "access_token": token,
            })
            post_id = r.get("post_id") or r.get("id") or ""
            permalink = None
            try:
                # photos return a photo id; fetch its permalink
                m = await _graph_get(client, post_id, {"fields": "permalink_url", "access_token": token})
                permalink = m.get("permalink_url")
            except MetaPublishError:
                pass

    log.info("influencer.fb.published", persona=persona_id, post_id=post_id, kind=kind)
    return FbPostResult(post_id=post_id, permalink=permalink, dry_run=False)
