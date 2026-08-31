"""HeyGen Video Agent client (no avatar) — SOCIAL-4.

Self-contained: this is NOT a media-factory engine/recipe. It talks to HeyGen's
Video Agent API directly (prompt + reference files -> generated clip), persists
the result to the brand's own Supabase Storage bucket via
`glitch_signal.media.generation.storage.upload_bytes`, and meters the spend
through the same `usage_events` choke point as the avatar engine
(`glitch_signal.media.generation.engines.heygen`).

API (verified from developers.heygen.com):
    POST {base}/v3/video-agents   X-Api-Key -> {data: {session_id, video_id: null, ...}}
    GET  {base}/v3/video-agents/{session_id}  -> {data: {video_id, ...}}   (poll until set)
    GET  {base}/v3/videos/{video_id}          -> {data: {status, video_url}}  (poll until completed)
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_API_BASE = os.environ.get("HEYGEN_API_BASE") or "https://api.heygen.com"
_API = f"{_API_BASE.rstrip('/')}/v3"
_MAX_FILES = 20


def build_video_prompt(idea: Idea) -> str:
    """Natural story + tone + orientation, positive framing only (no timestamps/questions/negations)."""
    body = f"{idea.hook}. " + " ".join(idea.key_points)
    return (
        f"{body}\n\n"
        "Tone: confident, sharp, honest — a trader done with hype, talking straight to camera's "
        "audience. Energetic but grounded.\n"
        "Use the attached brand assets and product screenshots for on-brand B-roll and overlays.\n"
        "Orientation: portrait."
    )[:10000]


def reference_urls(brand_id: str) -> list[str]:
    """Comma-separated `<PREFIX>_SOCIAL_REFERENCE_URLS`, capped at `_MAX_FILES`."""
    from glitch_signal.config import brand_env

    raw = brand_env("SOCIAL_REFERENCE_URLS", brand_id)
    return [u.strip() for u in raw.split(",") if u.strip()][:_MAX_FILES]


def _heygen_key() -> str:
    """Mirror `HeyGenEngine._key()` exactly: env var, not `settings()` (media/generation/engines/heygen.py)."""
    return (os.environ.get("HEYGEN_API_KEY") or "").strip()


def _heygen_headers() -> dict[str, str]:
    return {"X-Api-Key": _heygen_key(), "Content-Type": "application/json"}


async def _default_submit(prompt: str, file_urls: list[str]) -> str:
    import httpx

    body = {
        "prompt": prompt[:10000],
        "orientation": "portrait",
        "mode": "generate",
        "files": [{"type": "url", "url": u} for u in file_urls[:_MAX_FILES]],
    }
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{_API}/video-agents", headers=_heygen_headers(), json=body)
        r.raise_for_status()
        return (r.json() or {}).get("data", {})["session_id"]


async def _default_poll(session_id: str, *, sleep: Any = asyncio.sleep, timeout_s: int = 1800) -> str:
    import httpx

    headers = _heygen_headers()
    waited = 0
    async with httpx.AsyncClient(timeout=60) as c:
        video_id = None
        while waited < timeout_s:
            if video_id is None:
                r = await c.get(f"{_API}/video-agents/{session_id}", headers=headers)
                r.raise_for_status()
                video_id = (r.json() or {}).get("data", {}).get("video_id")
            if video_id:
                r = await c.get(f"{_API}/videos/{video_id}", headers=headers)
                r.raise_for_status()
                v = (r.json() or {}).get("data", {})
                status = str(v.get("status", "")).lower()
                if status == "completed":
                    return v["video_url"]
                if status in ("failed", "error"):
                    raise RuntimeError(f"heygen video {video_id} {status}: {v.get('error') or v.get('message') or ''}")
            await sleep(10)
            waited += 10
    raise TimeoutError(f"heygen session {session_id} timed out after {timeout_s}s")


async def _default_persist(brand_id: str, url: str) -> str:
    """Download the HeyGen mp4 and re-host it via the real storage helper (STORAGE-1).

    `glitch_signal.media.generation.storage.upload_bytes(data, brand_id, *, ext=, content_type=,
    prefix=, client=) -> str` is the real public signature (data first, brand_id second, `ext`
    not `suffix`, no leading dot) — confirmed by reading storage.py; the brief's
    `upload_bytes(brand_id, data, content_type=, suffix=)` guess does not match.
    """
    import httpx

    from glitch_signal.media.generation.storage import upload_bytes

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(url)
        r.raise_for_status()
        data = r.content
    return await upload_bytes(data, brand_id, ext="mp4", content_type="video/mp4", prefix="social_video")


async def _meter(brand_id: str, session_id: str) -> None:
    """Attribute this HeyGen Video Agent call to the brand (COST-METER). Never raises.

    Mirrors `media/generation/engines/heygen.py::_meter` — same `usage_events` choke point via
    `record_usage`, priced with the same `heygen_cost` book (no `model`/`avatar_id` concept for
    the Video Agent, so the vendor model tag is a static "video-agent").
    """
    try:
        from glitch_signal.analytics.cost.meter import record_usage
        from glitch_signal.analytics.cost.pricing import heygen_cost

        credits, cost = heygen_cost("video-agent")
        await record_usage(
            brand_id=brand_id,
            vendor="heygen",
            operation="video_agent.generate",
            model="video-agent",
            units={"credits": credits, "session_id": session_id},
            cost_usd=cost,
            request_id=session_id,
        )
    except Exception:  # noqa: BLE001 — metering never breaks generation
        pass


async def generate_video(
    brand_id: str,
    prompt: str,
    file_urls: list[str],
    *,
    submit: Any = None,
    poll: Any = None,
    persist_url: Any = None,
) -> str:
    """POST the Video Agent, poll to completion, persist to the brand bucket, return the durable URL."""
    submit = submit or _default_submit
    poll = poll or _default_poll
    persist_url = persist_url or _default_persist

    session_id = await submit(prompt, file_urls)
    heygen_url = await poll(session_id)
    out = await persist_url(brand_id, heygen_url)
    await _meter(brand_id, session_id)
    return out
