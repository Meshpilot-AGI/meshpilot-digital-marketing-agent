"""Reddit discovery client (TARGET-1) — find the conversations, and the rooms they happen in.

The agent's only sensing organ before this was CaptAPI, which covers Instagram and TikTok. For an
audience that lives on Reddit and X, that is the wrong organ: it can see trends in rooms this brand
has no reason to be in, and nothing at all in the rooms that matter.

Backed by **redditapis.com** (`REDDITAPIS_TOKEN`), verified live 2026-09-02. Reads only — public
posts and public community metadata. The same vendor offers comment/vote/DM writes behind an auth
route that takes a Reddit username and password; we deliberately do **not** use those. Writing to
Reddit goes through Zernio's OAuth connection instead, so no third party ever holds account
credentials (see `docs/plans/2026-09-02-targeting-and-distribution.md` §3).

⚠️ Reddit's own Data API is not an option here: its free tier is non-commercial only and names brand
monitoring as commercial, and the commercial tier starts around $12,000/month. This costs $0.002 per
read.

**Nothing in this module names a subreddit, an industry, or a brand.** Queries come from the caller
— ultimately from the brand's declared audience — which is what lets a second brand discover an
entirely different set of rooms with the same code.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = "https://api.redditapis.com"
_TIMEOUT_S = 30


def _token() -> str:
    tok = (os.environ.get("REDDITAPIS_TOKEN") or "").strip()
    if not tok:  # mirror captapi: fall back to Settings, since .env is not in os.environ locally
        try:
            from glitch_signal.config import settings

            tok = (getattr(settings(), "redditapis_token", "") or "").strip()
        except Exception:  # noqa: BLE001 — don't mask the clearer "not set" error below
            tok = ""
    if not tok:
        raise RuntimeError("REDDITAPIS_TOKEN not set — required for Reddit discovery")
    return tok


async def _get(path: str, params: dict[str, Any]) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.get(f"{_BASE}{path}", params={k: v for k, v in params.items() if v not in (None, "")},
                        headers={"Authorization": f"Bearer {_token()}"})
        if r.status_code >= 400:
            raise RuntimeError(f"redditapis {path} -> {r.status_code}: {r.text[:200]}")
        return r.json() or {}


def compact_post(p: dict) -> dict:
    """One post, reduced to what a targeting decision actually needs.

    Reddit returns a large object per post; the loop pays for every token of it. Kept: where it was
    said, how much traction it has, and enough text to judge relevance.
    """
    txt = str(p.get("text") or p.get("selftext") or "")
    return {
        "id": p.get("id"),
        "subreddit": p.get("subreddit"),
        "title": str(p.get("title") or "")[:200],
        "excerpt": txt[:400],
        "author": p.get("author"),
        "upvotes": p.get("upvotes") or p.get("score"),
        "comments": p.get("num_comments") or p.get("numComments"),
        "permalink": p.get("permalink") or p.get("url"),
        "created_utc": p.get("created_utc"),
    }


def compact_community(c: dict) -> dict:
    """One community, reduced to the fields a surface score is built from."""
    return {
        "name": c.get("name") or c.get("display_name"),
        "subscribers": c.get("subscribers") or c.get("members"),
        "title": str(c.get("title") or "")[:160],
        "description": str(c.get("description") or "")[:300],
        "over18": c.get("over18") or c.get("nsfw"),
    }


async def search_posts(query: str, *, subreddit: str | None = None, sort: str = "relevance",
                       limit: int = 25, time_window: str | None = None,
                       after: str | None = None) -> dict:
    """Search public Reddit posts. `sort` ∈ relevance|new|top; `time_window` ∈ hour|day|week|month|year|all.

    ⚠️ **`relevance` is the only sort that targets.** Measured on the same query, 2026-09-02:

    - `relevance` → "Stop giving your money to prop firms" (93↑), "What's the WORST rule a futures
      prop firm can have?", "Which prop firm rule has actually hurt your trading" — all on-topic.
    - `top` → r/apolloapp, r/nosleep, r/news. It returns all-time global top posts and all but
      ignores the query.
    - `new` → r/CrusaderKings and an anime subreddit for "firm rules drawdown"; recency wins over
      meaning.

    So the default is `relevance`, and it should stay that way. `new` is defensible ONLY when scoped
    to a `subreddit` ("what is fresh in this room"), where recency is the point and the room already
    supplies the relevance.

    Returns `{"posts": [...compact...], "after": cursor}` — `after` pages without re-running the query.
    """
    data = await _get("/api/reddit/search", {
        "q": query, "subreddit": subreddit, "sort": sort,
        "limit": max(1, min(int(limit), 100)), "t": time_window, "after": after,
    })
    posts = data.get("posts") or data.get("items") or []
    return {"posts": [compact_post(p) for p in posts if isinstance(p, dict)],
            "after": data.get("after")}


async def search_communities(query: str, *, limit: int = 25) -> dict:
    """Find the ROOMS, not the posts — the primitive behind surface discovery.

    Returns subscriber counts, which is the first input to scoring a surface: a room's size bounds
    how much reach participating there can ever be worth.
    """
    data = await _get("/api/reddit/search/communities", {
        "q": query, "limit": max(1, min(int(limit), 100)),
    })
    rows = data.get("communities") or data.get("items") or []
    return {"communities": [compact_community(c) for c in rows if isinstance(c, dict)],
            "after": data.get("after")}


async def user(username: str) -> dict:
    """Public profile for an account — the standing check behind the Reddit write gate.

    `u/glitchExecutor` measured 0 comment karma on a 4-month-old account (2026-09-02); subreddits
    filter exactly that profile via AutoModerator, so automated participation would be removed before
    anyone read it. TARGET-4 gates on these numbers rather than on a date.
    """
    data = await _get(f"/api/reddit/user/{username.lstrip('u/').strip()}", {})
    u = data.get("user") or data
    return {
        "name": u.get("name"),
        "created_utc": u.get("created_utc"),
        "total_karma": u.get("total_karma"),
        "link_karma": u.get("link_karma"),
        "comment_karma": u.get("comment_karma"),
        "has_verified_email": u.get("has_verified_email"),
        "is_suspended": u.get("is_suspended"),
    }
