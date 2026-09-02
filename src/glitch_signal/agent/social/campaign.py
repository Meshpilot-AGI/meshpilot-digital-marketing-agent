from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from glitch_signal.agent.social import matrix as _matrix
from glitch_signal.agent.social.spec import (
    IMAGE_MODEL,
    IMAGE_PLATFORMS,
    VIDEO_PLATFORMS,
    CampaignResult,
    PostDraft,
    derive_status,
)

log = structlog.get_logger(__name__)


# The video deadline must stay strictly UNDER the cron capability cap, or the outer
# `asyncio.wait_for` in `_run_capability` kills the whole run before our fail-soft fallback can
# demote to image-only. This margin covers the pre-video work (ideate/reserve/image) plus the
# post-video work (captions, conscience, fan-out, finalize) that still has to fit in the cap.
_VIDEO_DEADLINE_MARGIN_S = 180
_VIDEO_DEADLINE_MIN_S = 30


def _video_deadline_s() -> int:
    """Configured video timeout, CLAMPED so a mis-set value can never defeat the fallback."""
    from glitch_signal.agent.cron.service import CAPABILITY_TIMEOUT_S
    from glitch_signal.config import settings

    configured = int(getattr(settings(), "agent_social_video_timeout_s", 420))
    ceiling = max(_VIDEO_DEADLINE_MIN_S, CAPABILITY_TIMEOUT_S - _VIDEO_DEADLINE_MARGIN_S)
    return max(_VIDEO_DEADLINE_MIN_S, min(configured, ceiling))


def _social_enabled() -> bool:
    """The social kill-switch alone, WITHOUT the publish gate — what a dry run needs."""
    from glitch_signal.config import settings
    return bool(getattr(settings(), "agent_social_enabled", False))


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
    positioning: Callable[..., Any] | None = None


def _default_deps() -> RunDeps:
    from glitch_signal.agent import positioning as _positioning
    from glitch_signal.agent.loop import conscience
    from glitch_signal.agent.memory.store import remember
    from glitch_signal.agent.social import captions, ideate, publish, store, video
    from glitch_signal.analytics.cost import budget

    async def _voice(brand_id: str):
        from glitch_signal.agent import positioning as _pos
        from glitch_signal.agent.social.plan import BrandVoice
        return BrandVoice.from_brand(await _pos.get_visual(brand_id),
                                     await _pos.get_guardrails(brand_id))

    async def generate_image(brand_id: str, idea) -> str:
        """Route on what the post IS, then render it that way.

        Two routes, both grounded in the brand's own art direction: a conceptual idea goes to the
        image model with a brief REFINED from the loose idea (the step whose absence made the last
        campaign generic), and a structured idea — a comparison, a definition, a list — renders as a
        deterministic card where the type is exact. Neither is the default; `asset_kind` decides.
        """
        from glitch_signal.agent import positioning as _pos
        from glitch_signal.agent.loop import llm as _llm
        from glitch_signal.agent.social import plan as _plan
        from glitch_signal.media.generation.storage import upload_bytes
        from glitch_signal.media.render import card as _card
        from glitch_signal.media.render import layouts as _layouts

        from glitch_signal.agent import firms as _firms

        voice = await _voice(brand_id)
        tokens = await _pos.get_visual(brand_id)
        # Hand the author the VERIFIED thresholds for whichever firms this idea names. Without this
        # the model supplies the numbers itself, and a wrong figure here is a false claim about a
        # partner's product published under an affiliate relationship.
        named = _firms.mentioned(f"{idea.angle} {idea.hook} {' '.join(idea.key_points or [])}")
        rules = _firms.rules_block(await _firms.rules_for_names(named)) if named else ""
        p = await _plan.plan_asset(idea, asset_kind=idea.asset_kind, platform="instagram",
                                   voice=voice, positioning=await _pos.get(brand_id),
                                   firm_rules_block=rules, complete=_llm.complete)
        if p.route in ("image", "poster"):
            from glitch_signal.media.generation.engines.muapi import MuapiEngine
            url = await MuapiEngine().generate(IMAGE_MODEL, p.prompt,
                                               params={"aspect_ratio": p.aspect})
            import httpx
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.get(url)
                r.raise_for_status()
                data = r.content
            # Re-host: muapi output URLs expire, and a post that outlives its image is worse than no
            # post at all.
            return await upload_bytes(data, brand_id, ext="jpg", content_type="image/jpeg",
                                      prefix="social_image")

        png = _layouts.render(p.layout, _layouts.Spec(
            content=_layouts.Content(**{k: v for k, v in p.fields.items()}),
            fmt=str(tokens.get("format") or _card.DEFAULT_FORMAT),
            palette=_card.Palette.from_dict(tokens)))
        return await upload_bytes(png, brand_id, ext="png", content_type="image/png",
                                  prefix="social_card")

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
                   spend_now=_spend_now, positioning=_positioning.get)


async def _pick_cell(brand_id: str, d: "RunDeps", engine: Any):
    """The matrix cell this run should fill, or None if the matrix is unavailable.

    Degrades to None rather than failing: an agent that cannot read its sampling history should
    still post, just without the deliberate variation.
    """
    try:
        from glitch_signal.agent import positioning as _pos

        pillars = (await _pos.get_strategy(brand_id, engine=engine)).get("pillars") or []
        history = await d.store_mod.recent_choices(brand_id, engine=engine)
        return _matrix.next_cell(pillars, history)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.matrix_unavailable", error=str(exc)[:200])
        return None


async def run_campaign(brand_id: str, *, deps: RunDeps | None = None, dry_run: bool = False,
                       engine: Any = None) -> CampaignResult:
    """Run one campaign. With `dry_run`, produce the creative but NEVER publish.

    A preview has to be able to run while publishing is switched off — that is the whole point of
    it — so it gates on `agent_social_enabled` alone. The safety property is structural rather than
    conditional: a dry run never reaches `fan_out` at all, so there is no flag state in which it can
    reach a platform. It also skips the campaign reservation, so previewing an idea does not burn
    its dedup key and the real run can still use it.
    """
    from glitch_signal.config import settings
    d = deps or _default_deps()
    if dry_run:
        if not _social_enabled():
            return CampaignResult(idea=None, image_url=None, video_url=None,
                                  skipped_reason="social disabled")
    elif not _social_on():
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="social/publish disabled")
    allowed, reason = await d.budget_check(brand_id)
    if not allowed:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason=f"budget: {reason}")
    spent0 = await d.spend_now(brand_id)

    recent = await d.store_mod.recent_dedup_keys(brand_id, engine=engine)
    # Pick the least-sampled cell of the content matrix and make it binding. Left to choose freely
    # an LLM converges on the same shape run after run — and with no variation there is nothing for
    # the outcome data to compare, so the learning loop has no signal no matter how well it measures.
    cell = await _pick_cell(brand_id, d, engine)
    idea = await d.ideate(brand_id, recent_keys=recent,
                          directive=(_matrix.directive(cell) if cell else ""), engine=engine)
    if idea is None:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="no fresh idea")

    # RESERVE the campaign BEFORE any paid work — the DB unique(brand_id,dedup_key) is the dedup
    # authority, so two concurrent runs of the same idea can never both do paid work. A conflict
    # (no row returned) is a clean duplicate skip.
    # Record what was DECIDED alongside the campaign: without it the outcome data has nothing to
    # group by and no lesson drawn from it can be falsified.
    choices = {**(cell.as_choices() if cell else {}), "asset_kind": idea.asset_kind}
    cid = None if dry_run else await d.store_mod.reserve_campaign(brand_id, idea, choices=choices,
                                                                  engine=engine)
    if cid is None and not dry_run:
        return CampaignResult(idea=idea, image_url=None, video_url=None,
                              skipped_reason="duplicate idea (already reserved)")

    async def _finish(status: str, *, image_url: str | None = None, video_url: str | None = None,
                      posts: list | None = None, reason: str | None = None) -> CampaignResult:
        cost = max(0.0, (await d.spend_now(brand_id)) - spent0)
        if not dry_run:
            await d.store_mod.finalize_campaign(cid, status, cost, image_url=image_url,
                                                video_url=video_url, failure_reason=reason,
                                                engine=engine)
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
        deadline = _video_deadline_s()
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
        # Voice + prohibitions for the critic. Fetched here (not inside review) so one campaign makes
        # one read, and so a positioning failure lands in the same fail-soft branch as the facts.
        pos = await d.positioning(brand_id, engine=engine) if d.positioning else ""
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
            v = await d.review(f"Social post for {brand_id} ({dr.platform})", dr.caption,
                               facts=facts, positioning=pos)
        except Exception:  # noqa: BLE001
            v = {}
        verdict = str((v or {}).get("verdict") or "").lower()
        verdicts[dr.platform] = verdict if verdict in ("pass", "concerns", "escalate") else "escalate"

    if dry_run:
        # Structurally cannot publish: fan_out is never called on this path.
        return await _finish("preview", image_url=image_url, video_url=video_url,
                             reason=f"dry run — {len(drafts)} draft(s), verdicts={verdicts}")
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
