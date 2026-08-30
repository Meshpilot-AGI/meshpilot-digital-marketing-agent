"""CaptAPI client (DISCOVERY) — trending social content signals.

CaptAPI (captapi.com) is a purpose-built social-data REST API: trending reels/feed/hashtags/songs/
creators for Instagram + TikTok. Bearer auth (`CAPTAPI_KEY` = `capt_live_…`). Credit-metered;
`cache=true` (default) returns a free 24h cache hit. Read-only + external — the `discover_trending`
tool that uses this is **gated OFF by the policy** until `agent_discovery_enabled` is flipped, so the
ability ships inert (no pulls until deliberately enabled).
"""
from __future__ import annotations

import os

import httpx

_BASE = "https://api.captapi.com"

# (platform, kind) -> endpoint path
_ENDPOINTS: dict[tuple[str, str], str] = {
    ("instagram", "reels"): "/v1/instagram/trending-reels",
    ("tiktok", "feed"): "/v1/tiktok/trending-feed",
    ("tiktok", "hashtags"): "/v1/tiktok/popular-hashtags",
    ("tiktok", "songs"): "/v1/tiktok/popular-songs",
    ("tiktok", "creators"): "/v1/tiktok/popular-creators",
}


def _key() -> str:
    key = (os.environ.get("CAPTAPI_KEY") or "").strip()
    if not key:
        raise RuntimeError("CAPTAPI_KEY not set — required for discovery")
    return key


def endpoint_for(platform: str, kind: str) -> str | None:
    return _ENDPOINTS.get((platform.strip().lower(), kind.strip().lower()))


async def trending(platform: str, kind: str, *, country: str | None = None, cache: bool = True,
                   base: str | None = None, timeout_s: int = 40,
                   client: httpx.AsyncClient | None = None) -> dict:
    """GET a CaptAPI trending endpoint → the parsed `data` payload (raises on HTTP error).

    `cache=True` (default) uses CaptAPI's free 24h cache to conserve credits. `client` injectable
    for tests.
    """
    path = endpoint_for(platform, kind)
    if path is None:
        raise ValueError(f"unsupported discovery target {platform!r}/{kind!r}; options: {sorted(_ENDPOINTS)}")
    params = {"cache": "true" if cache else "false"}
    if country:
        params["country"] = country
    headers = {"Authorization": f"Bearer {_key()}"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await client.get(f"{(base or _BASE).rstrip('/')}{path}", params=params, headers=headers)
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"captapi {path} -> {r.status_code}: {r.text[:200]}")
    body = r.json()
    return body.get("data", body) if isinstance(body, dict) else body
