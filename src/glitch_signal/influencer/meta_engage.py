"""Sanctioned IG engagement transport via the Meta Graph API.

Fetches comments on the persona's OWN recent media and replies to them
through the same Page token meta_publish uses. Strictly owned-surface:
we only ever read/reply on the persona's own posts — no outbound action
on third-party accounts (the engagement_policy hard-guard lives in
engagement.py).

Graph endpoints:
  GET  /{ig_user_id}/media?fields=id,timestamp,permalink   (recent posts)
  GET  /{media_id}/comments?fields=id,text,username,timestamp,replies
  POST /{ig_comment_id}/replies   message=...              (public reply)

DM sending uses the IG Messaging API (conversations) and stays
draft-then-approve per policy — not auto-sent here.
"""
from __future__ import annotations

import datetime as _dt

import httpx
import structlog

from glitch_signal.influencer.engagement import InboundComment

log = structlog.get_logger(__name__)

_GRAPH = "https://graph.facebook.com"
import os as _os
_VER = _os.environ.get("META_GRAPH_API_VERSION", "v21.0")


async def fetch_recent_comments(
    ig_user_id: str, token: str, *, lookback_hours: int = 48, max_media: int = 10,
) -> list[InboundComment]:
    """Comments on the persona's own recent media, newest-relevant first.

    Skips comments authored by the account itself (our own replies) so we
    don't reply to ourselves."""
    out: list[InboundComment] = []
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=lookback_hours)
    async with httpx.AsyncClient(timeout=30) as c:
        media = (await c.get(f"{_GRAPH}/{_VER}/{ig_user_id}/media", params={
            "fields": "id,timestamp", "limit": str(max_media), "access_token": token,
        })).json()
        if "error" in media:
            raise RuntimeError(f"media list: {media['error'].get('message')}")
        # who are we (to skip our own comments)
        mej = (await c.get(f"{_GRAPH}/{_VER}/{ig_user_id}",
                           params={"fields": "username", "access_token": token})).json()
        self_user = (mej.get("username") or "").lower()
        for m in media.get("data", []):
            cj = (await c.get(f"{_GRAPH}/{_VER}/{m['id']}/comments", params={
                "fields": "id,text,username,timestamp", "limit": "50", "access_token": token,
            })).json()
            for cm in cj.get("data", []):
                ts = _parse_ts(cm.get("timestamp"))
                if ts and ts < cutoff:
                    continue
                if (cm.get("username") or "").lower() == self_user:
                    continue
                out.append(InboundComment(
                    id=cm["id"], text=cm.get("text", ""),
                    author=cm.get("username", ""),
                    created_at=ts or _dt.datetime.now(_dt.timezone.utc),
                    on_post_id=m["id"],
                ))
    return out


async def reply_to_comment(comment_id: str, message: str, token: str) -> str:
    """Public reply to a comment on the persona's own post. Returns reply id."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_GRAPH}/{_VER}/{comment_id}/replies",
                         data={"message": message, "access_token": token})
        j = r.json()
    if r.status_code >= 400 or "error" in j:
        raise RuntimeError(f"reply {comment_id}: {j.get('error', j)}")
    return j.get("id", "")


def _parse_ts(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        # IG returns e.g. 2026-06-04T20:00:35+0000
        return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
