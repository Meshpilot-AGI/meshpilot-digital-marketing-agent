from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from glitch_signal.agent.social.spec import (
    IMAGE_PLATFORMS,
    IMAGE_RECIPE,
    VIDEO_PLATFORMS,
    CampaignResult,
    PostDraft,
    derive_status,
)

log = structlog.get_logger(__name__)


def _social_on() -> bool:
    from glitch_signal.config import settings
    s = settings()
    return bool(getattr(s, "agent_social_enabled", False)
                and getattr(s, "agent_publish_enabled", False))


@dataclass
class RunDeps:
    ideate: Callable[..., Any]
    captions: Callable[..., Any]
    generate_image: Callable[..., Any]     # (brand_id, idea) -> url  (Higgsfield via media factory)
    generate_video: Callable[..., Any]     # (brand_id, idea) -> url  (HeyGen Video Agent client)
    review: Callable[..., Any]
    brand_facts: Callable[..., Any]
    budget_check: Callable[..., Any]
    fan_out: Callable[..., Any]
    store_mod: Any
    remember: Callable[..., Any]
    have_constitution: Callable[[], bool]
    spend_now: Callable[[str], Any]


def _default_deps() -> RunDeps:
    from glitch_signal.agent.loop import conscience
    from glitch_signal.agent.memory.store import remember
    from glitch_signal.agent.social import captions, ideate, publish, store, video
    from glitch_signal.analytics.cost import budget
    from glitch_signal.media.generation import generate as _generate
    from glitch_signal.media.generation.spec import Brief
    from glitch_signal.media.generation.storage import persist

    async def generate_image(brand_id: str, idea) -> str:
        asset = await _generate(Brief(brand_id=brand_id, recipe=IMAGE_RECIPE,
                                      inputs={"prompt": f"{idea.angle}: {idea.hook}"}))
        return (await persist(asset, brand_id)).url

    async def generate_video(brand_id: str, idea) -> str:
        return await video.generate_video(brand_id, video.build_video_prompt(idea),
                                          video.reference_urls(brand_id))

    async def _remember(brand_id, content):
        await remember(brand_id, "episode", content, source="social_campaign")

    async def _spend_now(brand_id: str) -> float:
        status = await budget.budget_status(brand_id)
        return float(status.get("spent_usd") or 0.0)

    return RunDeps(ideate=ideate.propose_idea, captions=captions.write_captions,
                   generate_image=generate_image, generate_video=generate_video,
                   review=conscience.review, brand_facts=conscience.brand_facts,
                   budget_check=budget.check, fan_out=publish.fan_out,
                   store_mod=store, remember=_remember,
                   have_constitution=lambda: bool(conscience.constitution()),
                   spend_now=_spend_now)


async def run_campaign(brand_id: str, *, deps: RunDeps | None = None,
                       engine: Any = None) -> CampaignResult:
    from glitch_signal.config import settings
    d = deps or _default_deps()
    if not _social_on():
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="social/publish disabled")
    allowed, reason = await d.budget_check(brand_id)
    if not allowed:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason=f"budget: {reason}")
    spent0 = await d.spend_now(brand_id)

    recent = await d.store_mod.recent_dedup_keys(brand_id, engine=engine)
    idea = await d.ideate(brand_id, recent_keys=recent, engine=engine)
    if idea is None:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="no fresh idea")

    # RESERVE the campaign BEFORE any paid work — the DB unique(brand_id,dedup_key) is the dedup
    # authority, so two concurrent runs of the same idea can never both do paid work. A conflict
    # (no row returned) is a clean duplicate skip.
    cid = await d.store_mod.reserve_campaign(brand_id, idea, engine=engine)
    if cid is None:
        return CampaignResult(idea=idea, image_url=None, video_url=None,
                              skipped_reason="duplicate idea (already reserved)")

    async def _finish(status: str, *, image_url: str | None = None, video_url: str | None = None,
                      posts: list | None = None, reason: str | None = None) -> CampaignResult:
        cost = max(0.0, (await d.spend_now(brand_id)) - spent0)
        await d.store_mod.finalize_campaign(cid, status, cost, image_url=image_url,
                                            video_url=video_url, failure_reason=reason, engine=engine)
        return CampaignResult(idea=idea, image_url=image_url, video_url=video_url,
                              posts=posts or [], cost_usd=cost, skipped_reason=reason)

    # media — per-medium fail-soft, with a budget RE-CHECK before each paid action so overlapping
    # or accumulating spend cannot blow past the cap mid-run.
    image_url = video_url = None
    if (await d.budget_check(brand_id))[0]:
        try:
            image_url = await d.generate_image(brand_id, idea)
        except Exception as exc:  # noqa: BLE001
            log.warning("social.image_failed", error=str(exc)[:200])
    if (await d.budget_check(brand_id))[0]:
        deadline = int(getattr(settings(), "agent_social_video_timeout_s", 420))
        try:
            # Bound video to a deadline well under the cron capability timeout: a slow HeyGen render
            # times out to IMAGE-ONLY (progress preserved) instead of the cron killing the whole run.
            video_url = await asyncio.wait_for(d.generate_video(brand_id, idea), timeout=deadline)
        except Exception as exc:  # noqa: BLE001 — incl. asyncio.TimeoutError
            log.warning("social.video_failed", error=str(exc)[:200])

    if not image_url and not video_url:
        return await _finish("failed", reason="media generation failed")

    # Caption / fact failures after paid media must NOT abort without recording the paid campaign.
    try:
        caps = await d.captions(brand_id, idea)
        facts = await d.brand_facts(brand_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.captions_or_facts_failed", error=str(exc)[:200])
        return await _finish("failed", image_url=image_url, video_url=video_url,
                             reason=f"caption/facts failed: {str(exc)[:150]}")

    drafts: list[PostDraft] = []
    if image_url:
        drafts += [PostDraft(p, "image", image_url, caps["image"]) for p in IMAGE_PLATFORMS]
    if video_url:
        drafts += [PostDraft(p, "video", video_url, caps["video"]) for p in VIDEO_PLATFORMS]
    drafts = drafts[:settings().agent_social_max_posts_per_run]

    # conscience gate — fail CLOSED: with a constitution loaded, a critic error/empty/unparseable
    # verdict HOLDS the post (escalate). No constitution → documented allow.
    have_constitution = d.have_constitution()
    verdicts: dict[str, str] = {}
    for dr in drafts:
        if not have_constitution:
            verdicts[dr.platform] = "pass"
            continue
        try:
            v = await d.review(f"Social post for {brand_id} ({dr.platform})", dr.caption, facts=facts)
        except Exception:  # noqa: BLE001
            v = {}
        verdict = str((v or {}).get("verdict") or "").lower()
        verdicts[dr.platform] = verdict if verdict in ("pass", "concerns", "escalate") else "escalate"

    posts = await d.fan_out(brand_id, cid, drafts, verdicts, engine=engine)
    result = await _finish(derive_status(posts), image_url=image_url, video_url=video_url, posts=posts)
    try:
        posted = sum(1 for p in posts if p.status == "posted")
        pending = sum(1 for p in posts if p.status == "pending")
        await d.remember(brand_id, f"social_campaign: {idea.angle} → {posted} posted / "
                                   f"{pending} pending / {len(posts)} total")
    except Exception:  # noqa: BLE001
        pass
    return result
