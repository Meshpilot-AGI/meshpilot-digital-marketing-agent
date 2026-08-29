"""Facebook Page publisher (Meta Graph API).

Publishes to a brand's Facebook Page. All credentials resolve PER-BRAND via
`config.brand_env` — there are no global keys:

    <PREFIX>_META_PAGE_ID        the target Page's id
    <PREFIX>_SYSTEM_USER_TOKEN   a Meta system-user token with publish access

We exchange the system-user token for the Page's access token, then post:

    text/link -> POST /{page_id}/feed     {message, [link]}
    image     -> POST /{page_id}/photos   {url, caption}
    video     -> POST /{page_id}/videos   {file_url, description}

Adapted from the Mesh Pilot monorepo (meshpilot_dashboard social_dispatch +
social_agent influencer.meta_publish).
"""
from __future__ import annotations

import httpx
import structlog

from glitch_signal.config import brand_env, settings

log = structlog.get_logger(__name__)

_GRAPH = "https://graph.facebook.com"


def _base(page_id: str) -> str:
    return f"{_GRAPH}/{settings().meta_graph_api_version}/{page_id}"


def resolve_facebook_creds(brand_id: str | None = None) -> tuple[str, str]:
    """(page_id, system_user_token) for the brand, from brand_env. Raises if unset."""
    page_id = brand_env("META_PAGE_ID", brand_id)
    system_user_token = brand_env("SYSTEM_USER_TOKEN", brand_id)
    if not page_id:
        raise RuntimeError("facebook: <PREFIX>_META_PAGE_ID is not set for this brand.")
    if not system_user_token:
        raise RuntimeError("facebook: <PREFIX>_SYSTEM_USER_TOKEN is not set for this brand.")
    return page_id, system_user_token


def build_post(
    page_id: str,
    page_token: str,
    *,
    message: str | None = None,
    link: str | None = None,
    image_url: str | None = None,
    video_url: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Pure: pick the Graph endpoint + form payload for the given content.

    Returns (url, form_data). Image wins over video wins over text if several
    are passed (callers normally pass exactly one content kind).
    """
    base = _base(page_id)
    if image_url:
        data = {"url": image_url, "access_token": page_token}
        if message:
            data["caption"] = message
        return f"{base}/photos", data
    if video_url:
        data = {"file_url": video_url, "access_token": page_token}
        if message:
            data["description"] = message
        return f"{base}/videos", data
    if not message:
        raise ValueError("facebook: a text post needs `message`.")
    data = {"message": message, "access_token": page_token}
    if link:
        data["link"] = link
    return f"{base}/feed", data


async def _fetch_page_token(page_id: str, system_user_token: str) -> str:
    """Exchange a system-user token for the Page's access token."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Token in the Authorization header, not the query string, so it never
        # lands in access logs / Sentry span URLs. Graph API accepts Bearer.
        r = await client.get(
            _base(page_id),
            params={"fields": "access_token"},
            headers={"Authorization": f"Bearer {system_user_token}"},
        )
        if r.status_code >= 400:
            log.error("facebook.page_token_failed", status=r.status_code, body=r.text[:500])
            r.raise_for_status()
        token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"facebook: no page access_token returned for page {page_id}")
    return token


async def publish_facebook(
    *,
    brand_id: str | None = None,
    message: str | None = None,
    link: str | None = None,
    image_url: str | None = None,
    video_url: str | None = None,
) -> tuple[str, str]:
    """Publish to the brand's Facebook Page. Returns (post_id, permalink)."""
    if settings().is_dry_run:
        log.info("facebook.publish.dry_run", brand_id=brand_id, has_message=bool(message))
        return "fb-dry-run", ""
    page_id, system_user_token = resolve_facebook_creds(brand_id)
    page_token = await _fetch_page_token(page_id, system_user_token)
    url, data = build_post(
        page_id,
        page_token,
        message=message,
        link=link,
        image_url=image_url,
        video_url=video_url,
    )
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, data=data)
        if r.status_code >= 400:
            log.error("facebook.publish_failed", url=url, status=r.status_code, body=r.text[:500])
            r.raise_for_status()
        j = r.json()
    post_id = j.get("post_id") or j.get("id") or ""
    permalink = f"https://www.facebook.com/{post_id}" if post_id else ""
    log.info("facebook.published", page_id=page_id, post_id=post_id)
    return post_id, permalink
