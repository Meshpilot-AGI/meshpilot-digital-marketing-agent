from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from glitch_signal.agent.social.spec import PlatformResult, PostDraft

log = structlog.get_logger(__name__)

_BUFFER_SERVICES = {"x", "linkedin", "tiktok"}   # everything else → Meta
_MARK_RESULT_ATTEMPTS = 4
_MARK_RESULT_BACKOFF_S = 0.5


def _correlation_key(campaign_id: str, platform: str) -> str:
    """Deterministic-prefix, unique correlation key minted BEFORE the provider call.

    (campaign_id, platform) is already the outbox's uniqueness constraint, so the prefix makes an
    orphaned provider-side post self-identifying; the random suffix keeps a retry of a genuinely
    new attempt distinguishable from the original.
    """
    return f"gsa-{campaign_id}-{platform}-{uuid.uuid4().hex[:8]}"


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

    # OUTBOX: reserve the row (status='pending') BEFORE the external publish, carrying a
    # correlation key WE generate up front. The provider assigns its own id only on success, so the
    # key is the one identifier that exists on both sides of the call and survives losing the
    # response — see `_correlation_key`.
    idem_key = _correlation_key(campaign_id, p)
    inserted = await store_mod.mark_pending(campaign_id, p, draft.media_kind, draft.caption,
                                            verdict, idem_key=idem_key, engine=engine)
    if not inserted:
        return PlatformResult(platform=p, status="skipped", verdict=verdict)

    pid: str | None = None
    url: str | None = None
    error: str | None = None
    try:
        if p in _BUFFER_SERVICES:
            pid, _ = await deps.buffer_create(brand_id, p, text=draft.caption,
                                              media_url=draft.media_url, idem_key=idem_key)
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
    # Persist the outcome, RETRYING — this write carries the provider id, and losing it strands a
    # real published post as an un-pollable 'pending' row forever. A transient DB blip must not be
    # swallowed on the first try. Isolated per-platform so a DB error never aborts the fan-out.
    await _mark_result_durably(store_mod, campaign_id, p, status, pid=pid, url=url, error=error,
                               idem_key=idem_key, engine=engine)
    return r


async def _mark_result_durably(store_mod: Any, campaign_id: str, platform: str, status: str, *,
                               pid: str | None, url: str | None, error: str | None,
                               idem_key: str, engine: Any = None) -> bool:
    """Write the publish outcome with bounded retries. Returns True if it landed.

    On exhaustion the row stays 'pending' by design: if a provider id was assigned the reconciler
    will resolve it from the provider, and if not, `idem_key` is the handle for manual recovery.
    Either way we never republish, so the worst case is a delayed status, not a duplicate post.
    """
    delay = _MARK_RESULT_BACKOFF_S
    for attempt in range(1, _MARK_RESULT_ATTEMPTS + 1):
        try:
            await store_mod.mark_result(campaign_id, platform, status, platform_post_id=pid,
                                        post_url=url, error=error, engine=engine)
            return True
        except Exception as exc:  # noqa: BLE001
            last = attempt == _MARK_RESULT_ATTEMPTS
            log.warning("social.mark_result_retry", platform=platform, status=status,
                        attempt=attempt, giving_up=last, error=str(exc)[:200])
            if last:
                # Loud: a delivered post whose terminal state we could not record. `idem_key` and
                # the provider id are both here so the row can be reconciled by hand if needed.
                log.error("social.mark_result_lost", platform=platform, status=status,
                          campaign_id=campaign_id, platform_post_id=pid, idem_key=idem_key)
                return False
            await asyncio.sleep(delay)
            delay *= 2
    return False


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
