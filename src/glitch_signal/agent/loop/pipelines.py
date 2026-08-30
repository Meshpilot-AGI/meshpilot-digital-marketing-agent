"""Pipelines (PIPELINE) — deliberate, scoped, scheduled agent runs.

A *pipeline* is the only place a capability turns on for real: a named run with a fixed SCOPE, a
goal, a cadence, and the kill-switches it requires. Capabilities are reachable from a pipeline, not
from a free-roaming agent — which is the whole point of scoping. Everything a pipeline relies on is
already enforced elsewhere: SCOPE bounds the offered *and* dispatched toolset (`scopes`), the policy
gate bounds effects (publish/discovery default-off) and spend (per-run caps), and a self-scheduled
follow-up is clamped to ⊆ the pipeline's scope (`cron.tool`). This module only *composes* those into
three concrete jobs — discovery, content, orm — as a declarative, versioned registry (mirrors
`scopes.py`). Nothing here runs autonomously: the manual trigger is operator-initiated, and seeded
schedules fire only when `agent_cron_enabled` is on.
"""
from __future__ import annotations

from dataclasses import dataclass

from glitch_signal.config import settings


@dataclass(frozen=True)
class Pipeline:
    name: str
    scope: str            # a `scopes` scope name — bounds the run's toolset
    goal: str             # instruction for the run; `{brand}` templated at trigger time
    max_steps: int
    schedule_kind: str    # scheduler kind for a seeded cron job: "cron" | "every"
    schedule: dict        # scheduler dict for that kind (e.g. {"cron_expr": "0 13 * * *"})
    requires: tuple[str, ...] = ()   # config flags that must be truthy for this pipeline to RUN

    def render_goal(self, brand: str) -> str:
        return self.goal.format(brand=brand)

    def missing_requirements(self) -> list[str]:
        """Required kill-switches that are currently off (empty list = runnable)."""
        s = settings()
        return [flag for flag in self.requires if not getattr(s, flag, False)]


# ── goals (each ends with an explicit DO-NOT boundary; the effect gates enforce it too) ──
_DISCOVERY_GOAL = (
    "Discovery run for brand '{brand}'. First recall what you already know about {brand}'s niche, "
    "audience and voice. Then use discover_trending to pull CURRENT trending signals on the platforms "
    "that matter for {brand}. For each strong signal, distill WHY it works — the hook, the format, the "
    "angle — and `remember` it as a concise, brand-tagged content-angle note. Do NOT generate media or "
    "publish anything; this run only gathers and distills inspiration for later content runs."
)
_CONTENT_DRAFT_GOAL = (
    "Content run for brand '{brand}' (caption-first). Recall the freshest trend/angle notes and the "
    "brand's voice and offer. Draft 2-3 short content pieces adapting those angles to {brand}'s voice: "
    "for each, write and polish the caption/copy plus a one-line MEDIA BRIEF describing the image or "
    "video to produce. Do NOT generate media and do NOT publish — `remember` each as a draft for human "
    "review."
)
_CONTENT_MEDIA_GOAL = (
    "Content run for brand '{brand}'. Recall the freshest trend/angle notes and the brand's voice and "
    "offer. Draft 2-3 content pieces adapting those angles to {brand}'s voice: for each, write the "
    "polished caption AND generate the matching image/video with the media tools. Do NOT publish — "
    "`remember` each finished draft for human review."
)
_ORM_GOAL = (
    "Reputation run for brand '{brand}'. Search the web for recent mentions, reviews and discussion of "
    "{brand}. Assess sentiment and surface anything that needs a response. For each issue, draft a "
    "suggested reply in {brand}'s voice and `remember` it together with the source link. Do NOT post or "
    "email — drafts only."
)


def registry() -> dict[str, Pipeline]:
    """Build the pipeline registry. The `content` pipeline resolves caption-first (scope
    `content_draft`, no paid media) unless `agent_content_media_enabled` is flipped on."""
    media_on = bool(getattr(settings(), "agent_content_media_enabled", False))
    return {
        "discovery": Pipeline(
            name="discovery", scope="discovery", goal=_DISCOVERY_GOAL, max_steps=6,
            schedule_kind="cron", schedule={"cron_expr": "0 13 * * *"},   # daily 13:00 UTC
            requires=("agent_discovery_enabled",)),
        "content": Pipeline(
            name="content",
            scope="content" if media_on else "content_draft",
            goal=_CONTENT_MEDIA_GOAL if media_on else _CONTENT_DRAFT_GOAL, max_steps=8,
            schedule_kind="cron", schedule={"cron_expr": "30 14 * * *"}),  # daily 14:30 UTC (after discovery)
        "orm": Pipeline(
            name="orm", scope="orm", goal=_ORM_GOAL, max_steps=6,
            schedule_kind="cron", schedule={"cron_expr": "0 15 * * *"}),   # daily 15:00 UTC
    }


def names() -> list[str]:
    return list(registry().keys())


def resolve(name: str | None) -> Pipeline | None:
    """Resolve a pipeline by name (case-insensitive). Unknown → None."""
    return registry().get((name or "").strip().lower())
