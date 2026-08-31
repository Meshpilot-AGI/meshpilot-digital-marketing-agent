from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from glitch_signal.agent.social.spec import PlatformResult, PostDraft

log = structlog.get_logger(__name__)

_BUFFER_SERVICES = {"x", "linkedin", "tiktok"}   # everything else → Meta


@dataclass
class Publishers:
    buffer_create: Callable[..., Awaitable[tuple[str, str | None]]]
    facebook: Callable[..., Awaitable[tuple[str, str | None]]]
    instagram: Callable[..., Awaitable[tuple[str, str | None]]]


def _default_publishers() -> Publishers:
    from glitch_signal.platforms.buffer import create_post
    from glitch_signal.platforms.facebook import publish_facebook
    from glitch_signal.platforms.instagram import publish_instagram
    return Publishers(buffer_create=create_post, facebook=publish_facebook,
                      instagram=publish_instagram)


async def publish_one(brand_id: str, campaign_id: str, draft: PostDraft, *, verdict: str,
                      deps: Publishers, store_mod: Any = None, engine: Any = None) -> PlatformResult:
    from glitch_signal.agent.social import store as _store
    store_mod = store_mod or _store
    p = draft.platform
    if verdict == "escalate":
        r = PlatformResult(platform=p, status="held", verdict=verdict)
        await store_mod.record_post(campaign_id, r, draft.media_kind, draft.caption, engine=engine)
        return r
    if await store_mod.already_posted(campaign_id, p, engine=engine):
        return PlatformResult(platform=p, status="skipped", verdict=verdict)
    try:
        if p in _BUFFER_SERVICES:
            pid, _ = await deps.buffer_create(brand_id, p, text=draft.caption, media_url=draft.media_url)
            url = None
        elif p == "facebook":
            pid, url = await deps.facebook(brand_id=brand_id, message=draft.caption,
                                           image_url=draft.media_url)
        elif p == "instagram":
            pid, url = await deps.instagram(brand_id=brand_id, caption=draft.caption,
                                            video_url=draft.media_url)
        else:
            return PlatformResult(platform=p, status="failed", verdict=verdict,
                                  error=f"unknown platform {p!r}")
        r = PlatformResult(platform=p, status="posted", verdict=verdict,
                           platform_post_id=pid, post_url=url)
    except Exception as exc:  # noqa: BLE001 — one platform failing never aborts the rest
        log.warning("social.publish_failed", platform=p, error=str(exc)[:200])
        r = PlatformResult(platform=p, status="failed", verdict=verdict, error=str(exc)[:200])
    await store_mod.record_post(campaign_id, r, draft.media_kind, draft.caption, engine=engine)
    return r


async def fan_out(brand_id: str, campaign_id: str, drafts: list[PostDraft],
                  verdicts: dict[str, str], *, deps: Publishers | None = None,
                  store_mod: Any = None, engine: Any = None) -> list[PlatformResult]:
    deps = deps or _default_publishers()
    out: list[PlatformResult] = []
    for d in drafts:
        out.append(await publish_one(brand_id, campaign_id, d,
                                     verdict=verdicts.get(d.platform, "concerns"),
                                     deps=deps, store_mod=store_mod, engine=engine))
    return out
