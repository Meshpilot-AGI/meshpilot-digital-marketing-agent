from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import structlog

from glitch_signal.agent.social.spec import (
    IMAGE_PLATFORMS,
    IMAGE_RECIPE,
    VIDEO_PLATFORMS,
    CampaignResult,
    PostDraft,
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

    return RunDeps(ideate=ideate.propose_idea, captions=captions.write_captions,
                   generate_image=generate_image, generate_video=generate_video,
                   review=conscience.review, brand_facts=conscience.brand_facts,
                   budget_check=budget.check, fan_out=publish.fan_out,
                   store_mod=store, remember=_remember)


async def run_campaign(brand_id: str, *, deps: RunDeps | None = None,
                       engine: Any = None) -> CampaignResult:
    d = deps or _default_deps()
    if not _social_on():
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="social/publish disabled")
    allowed, reason = await d.budget_check(brand_id)
    if not allowed:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason=f"budget: {reason}")

    recent = await d.store_mod.recent_dedup_keys(brand_id, engine=engine)
    idea = await d.ideate(brand_id, recent_keys=recent, engine=engine)
    if idea is None:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="no fresh idea")

    # media — per-medium fail-soft (image = Higgsfield/factory; video = HeyGen Video Agent)
    image_url = video_url = None
    try:
        image_url = await d.generate_image(brand_id, idea)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.image_failed", error=str(exc)[:200])
    try:
        video_url = await d.generate_video(brand_id, idea)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.video_failed", error=str(exc)[:200])
    if not image_url and not video_url:
        return CampaignResult(idea=idea, image_url=None, video_url=None,
                              skipped_reason="media generation failed")

    caps = await d.captions(brand_id, idea)
    facts = await d.brand_facts(brand_id)

    drafts: list[PostDraft] = []
    if image_url:
        drafts += [PostDraft(p, "image", image_url, caps["image"]) for p in IMAGE_PLATFORMS]
    if video_url:
        drafts += [PostDraft(p, "video", video_url, caps["video"]) for p in VIDEO_PLATFORMS]

    # Per-run post cap (spec: agent_social_max_posts_per_run) — enforced here because the
    # brief's drafts list has no upper bound of its own before the conscience gate.
    from glitch_signal.config import settings
    drafts = drafts[:settings().agent_social_max_posts_per_run]

    # conscience gate per intended post → verdict map
    verdicts: dict[str, str] = {}
    for dr in drafts:
        try:
            v = await d.review(f"Social post for {brand_id} ({dr.platform})", dr.caption, facts=facts)
        except Exception:  # noqa: BLE001 — critic error → fail toward not posting
            v = {"verdict": "escalate"}
        verdicts[dr.platform] = str((v or {}).get("verdict") or "pass")  # {}=no constitution → allowed

    cid = await d.store_mod.create_campaign(brand_id, idea, image_url=image_url,
                                            video_url=video_url, engine=engine)
    posts = await d.fan_out(brand_id, cid, drafts, verdicts, engine=engine)

    posted = sum(1 for p in posts if p.status == "posted")
    status = ("posted" if posted == len(posts) and posts
              else "partial" if posted else "held")
    await d.store_mod.finalize_campaign(cid, status, 0.0, engine=engine)
    try:
        await d.remember(brand_id, f"social_campaign: {idea.angle} → {posted}/{len(posts)} posted")
    except Exception:  # noqa: BLE001
        pass
    return CampaignResult(idea=idea, image_url=image_url, video_url=video_url, posts=posts)
