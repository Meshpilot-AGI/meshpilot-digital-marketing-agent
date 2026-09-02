"""Read back what a published post actually achieved.

The publishing clients are write-only; nothing in the codebase ever asked a platform how a post
performed. This is the read side, and it is deliberately thin: fetch the numbers, normalise the
names, hand back a dict. Interpretation belongs to the learning loop, not here.

Coverage is honest rather than uniform. Meta (Facebook Pages, Instagram) exposes per-post insights
on the same Graph credentials we already publish with, so those are real. Posts routed through
Buffer (X, LinkedIn, TikTok) are NOT covered: Buffer's API returns delivery status and an
`externalLink`, not analytics, so metrics for those would need each platform's own API and its own
app review. Returning nothing for them is correct — a fabricated zero would poison the loop far
worse than a gap, because "no engagement" and "not measured" would become indistinguishable.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from glitch_signal.config import settings
from glitch_signal.platforms.facebook import resolve_facebook_creds

log = structlog.get_logger(__name__)

_GRAPH = "https://graph.facebook.com"
_TIMEOUT_S = 30.0

# Platforms we can actually measure. Anything else yields None (not zero) — see the module docstring.
MEASURABLE = ("facebook", "instagram")

# VERIFIED by probing each name individually against the live Page — not taken from docs.
# `post_impressions`, `post_impressions_unique`, `post_engaged_users`, `post_views` and `post_reach`
# ALL return "(#100) The value must be a valid insights metric", and re-probing on v21, v23 and v26
# gives the identical result — so this is NOT the version pin, and bumping the API version will not
# recover them. The remaining explanation is the app lacking `read_insights` (App Review) and/or
# Meta suppressing distribution metrics below an audience threshold.
#
# Consequence, stated plainly: the loop learns from ENGAGEMENT, not distribution. That is arguably
# the better signal anyway — reach is mostly the algorithm's choice, engagement is the post's.
_FB_METRICS = ("post_clicks", "post_reactions_by_type_total", "post_activity_by_action_type",
               "post_video_views")
_IG_METRICS = ("reach", "likes", "comments", "saves", "shares", "views")


def _base() -> str:
    return f"{_GRAPH}/{settings().meta_graph_api_version}"


def _auth(token: str) -> dict[str, str]:
    """Carry the token in a HEADER, never a query parameter.

    httpx puts the full request URL into `HTTPStatusError.__str__`, so a token in the query string
    lands in every logged error — and these calls log on failure by design. Graph accepts bearer
    auth, so the fix is to stop putting the secret somewhere that gets printed.
    """
    return {"Authorization": f"Bearer {token}"}


def _safe(exc: Exception) -> str:
    """Error text with any surviving credential redacted. Defence in depth: a library we do not
    control may still echo a URL we did not construct."""
    import re

    return re.sub(r"(access_token|Bearer)=?[=\s]*[A-Za-z0-9._\-]+", r"\1=<redacted>",
                  str(exc))[:200]


def _insight_map(payload: dict) -> dict[str, Any]:
    """Flatten Graph's [{name, values:[{value}]}] shape into {name: value}."""
    out: dict[str, Any] = {}
    for row in (payload or {}).get("data", []) or []:
        vals = row.get("values") or []
        if vals:
            out[row.get("name", "")] = vals[0].get("value")
    return out


async def _page_token(page_id: str, system_token: str, c: httpx.AsyncClient) -> str | None:
    """Exchange the system-user token for a PAGE access token.

    Publishing works with the system-user token, but insights does not: Graph rejects it with
    "User Access Token Is Not Supported" (code 190 / subcode 2069032). The page's own token is
    fetched with the system-user token, so this needs no extra credential — just the extra hop that
    the write path never had to make.
    """
    try:
        r = await c.get(f"{_base()}/{page_id}", params={"fields": "access_token"},
                        headers=_auth(system_token))
        r.raise_for_status()
        return (r.json() or {}).get("access_token")
    except Exception as exc:  # noqa: BLE001
        log.warning("insights.page_token_failed", error=_safe(exc))
        return None


async def facebook_post(post_id: str, *, brand_id: str | None = None,
                        client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    """Engagement for one Page post, or None if it cannot be read. Impressions/reach unavailable."""
    try:
        page_id, system_token = resolve_facebook_creds(brand_id)
    except Exception as exc:  # noqa: BLE001 — an unconfigured brand is not measurable, not an error
        log.warning("insights.fb_creds_missing", error=str(exc)[:160])
        return None
    own = client is None
    c = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        token = await _page_token(page_id, system_token, c)
        if not token:
            return None
        ins = await c.get(f"{_base()}/{post_id}/insights",
                          params={"metric": ",".join(_FB_METRICS)}, headers=_auth(token))
        ins.raise_for_status()
        m = _insight_map(ins.json())
        # Reactions come back as a per-type dict; the loop wants one comparable number.
        reactions = m.get("post_reactions_by_type_total") or {}
        likes = sum(v for v in reactions.values() if isinstance(v, (int, float))) if isinstance(reactions, dict) else None
        eng = await c.get(f"{_base()}/{post_id}",
                          params={"fields": "comments.summary(true),shares,reactions.summary(true)"},
                          headers=_auth(token))
        eng.raise_for_status()
        e = eng.json()
        # Reactions via the summary are more reliable than the insights breakdown, which comes back
        # as an empty dict on a post with none.
        summary_likes = ((e.get("reactions") or {}).get("summary") or {}).get("total_count")
        return {
            # impressions / reach deliberately absent — see _FB_METRICS. Leaving them out entirely
            # keeps NULL meaning "not measured" rather than implying we looked and found none.
            "clicks": m.get("post_clicks"),
            "likes": summary_likes if summary_likes is not None else likes,
            "comments": ((e.get("comments") or {}).get("summary") or {}).get("total_count"),
            "shares": (e.get("shares") or {}).get("count"),
            "video_views": m.get("post_video_views"),
            "raw": {"insights": m, "engagement": e},
        }
    except Exception as exc:  # noqa: BLE001 — a metrics read must never disturb anything else
        log.warning("insights.fb_failed", post_id=post_id, error=_safe(exc))
        return None
    finally:
        if own:
            await c.aclose()


async def instagram_media(media_id: str, *, brand_id: str | None = None,
                          client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    """Reach/likes/comments/saves/shares/views for one IG media, or None if it cannot be read."""
    try:
        _page, token = resolve_facebook_creds(brand_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("insights.ig_creds_missing", error=str(exc)[:160])
        return None
    own = client is None
    c = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        r = await c.get(f"{_base()}/{media_id}/insights",
                        params={"metric": ",".join(_IG_METRICS)}, headers=_auth(token))
        r.raise_for_status()
        m = _insight_map(r.json())
        return {
            "impressions": m.get("views"),      # IG retired `impressions`; `views` is the successor
            "reach": m.get("reach"),
            "likes": m.get("likes"),
            "comments": m.get("comments"),
            "saves": m.get("saves"),
            "shares": m.get("shares"),
            "video_views": m.get("views"),
            "raw": {"insights": m},
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("insights.ig_failed", media_id=media_id, error=_safe(exc))
        return None
    finally:
        if own:
            await c.aclose()


async def fetch(platform: str, provider_post_id: str, *, brand_id: str | None = None,
                client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    """Dispatch to the right reader. None means NOT MEASURED — never treat it as zero."""
    p = (platform or "").lower()
    if p == "facebook":
        return await facebook_post(provider_post_id, brand_id=brand_id, client=client)
    if p == "instagram":
        return await instagram_media(provider_post_id, brand_id=brand_id, client=client)
    return None
