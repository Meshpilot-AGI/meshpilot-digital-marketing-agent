from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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

    # Conscience hard-gate: an escalated post is a terminal HOLD, never published.
    if verdict == "escalate":
        r = PlatformResult(platform=p, status="held", verdict=verdict)
        await store_mod.record_post(campaign_id, r, draft.media_kind, draft.caption, engine=engine)
        return r

    # OUTBOX: reserve the row (status='pending') BEFORE the external publish. If it already exists,
    # a prior attempt is in-flight/terminal — do NOT blindly republish an uncertain request.
    inserted = await store_mod.mark_pending(campaign_id, p, draft.media_kind, draft.caption,
                                            verdict, engine=engine)
    if not inserted:
        return PlatformResult(platform=p, status="skipped", verdict=verdict)

    pid: str | None = None
    url: str | None = None
    error: str | None = None
    try:
        if p in _BUFFER_SERVICES:
            pid, _ = await deps.buffer_create(brand_id, p, text=draft.caption, media_url=draft.media_url)
            # Buffer returns "sending" — NOT a terminal delivered state. Record it as pending
            # (with the request id) until a reconciler confirms Buffer reports a sent result.
            status = "pending"
        elif p == "facebook":
            pid, url = await deps.facebook(brand_id=brand_id, message=draft.caption,
                                           image_url=draft.media_url)
            status = "posted"   # Meta returns a real post id synchronously → terminal
        elif p == "instagram":
            pid, url = await deps.instagram(brand_id=brand_id, caption=draft.caption,
                                            video_url=draft.media_url)
            status = "posted"
        else:
            status, error = "failed", f"unknown platform {p!r}"
    except Exception as exc:  # noqa: BLE001 — one platform failing never aborts the rest
        log.warning("social.publish_failed", platform=p, error=str(exc)[:200])
        status, error = "failed", str(exc)[:200]

    r = PlatformResult(platform=p, status=status, verdict=verdict,
                       platform_post_id=pid, post_url=url, error=error)
    # Persist the outcome. If THIS fails after a successful external publish, the side effect is
    # not lost — the durable 'pending' outbox row (with the request id) already exists — and we do
    # NOT republish. Isolated per-platform so a DB error never aborts the rest of the fan-out.
    try:
        await store_mod.mark_result(campaign_id, p, status, platform_post_id=pid,
                                    post_url=url, error=error, engine=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.mark_result_failed", platform=p, status=status, error=str(exc)[:200])
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
