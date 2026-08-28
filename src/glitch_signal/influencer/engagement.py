"""Engagement engine for the influencer pipeline — sanctioned surfaces only.

Implements the engagement_policy block from the persona bible, staying
strictly inside platform automation guidelines (no outbound bots, no IP
tricks, no browser automation). All actions are on the creator's OWN
owned surfaces:

  own_comment_reply = auto_after_window
      Reply to comments on the persona's OWN posts, but only after a
      grace window (so it reads human, not instant-bot). Drafts in the
      persona voice; auto-sends once the window has elapsed.

  inbound_dm = draft_then_approve
      Draft a reply to an inbound DM; queue it for operator approval
      rather than auto-sending.

  comment_to_dm_funnel = true
      When a comment is a question, the reply answers briefly and invites
      the person to DM (the highest-signal owned action on IG Reels).

  outbound_engagement = disabled
      NEVER auto-comment / auto-like on other accounts. Enforced here as
      a hard guard regardless of caller.

The actual fetch/send transport is pluggable (Upload-Post comments API /
platform Graph API) and defaults to dry-run, so this module is safe to
run before per-brand messaging OAuth is wired.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any, Literal

import structlog

from glitch_signal.influencer.llm import complete as complete_with_fallback
from glitch_signal.config import settings
from glitch_signal.influencer.persona import Persona, load_persona

log = structlog.get_logger(__name__)

ActionKind = Literal["comment_reply", "dm_reply_draft", "skip"]

_QUESTION = re.compile(r"\?|\b(how|what|why|when|where|which|can i|should i|is it|does)\b", re.I)


@dataclass(slots=True)
class InboundComment:
    id: str
    text: str
    author: str
    created_at: _dt.datetime
    on_post_id: str


@dataclass(slots=True)
class InboundDM:
    id: str
    text: str
    author: str
    created_at: _dt.datetime


@dataclass(slots=True)
class EngagementAction:
    kind: ActionKind
    target_id: str
    draft: str
    auto_send: bool          # True => engine may send now; False => needs approval
    reason: str
    funnel_to_dm: bool = False


def _policy(persona: Persona) -> dict[str, Any]:
    return persona.raw.get("engagement_policy") or {}


def _disclosure(persona: Persona) -> str:
    return persona.raw.get("disclosure") or ""


def _is_question(text: str) -> bool:
    return bool(_QUESTION.search(text or ""))


async def _draft_reply(
    persona: Persona, text: str, *, funnel: bool, channel: str,
) -> str:
    system = (
        f"You are {persona.display_name}, {persona.archetype}. Reply in your "
        "authentic, warm, concise voice. This is general education, NOT "
        "individual medical advice — never diagnose. One or two sentences. "
        + ("End by warmly inviting them to DM you for more. " if funnel else "")
        + "No hashtags, no emoji spam (at most one)."
    )
    user = f"Someone wrote on your {channel}: \"{text}\"\nWrite your reply."
    reply = await complete_with_fallback(
        user, tier="smart", system=system, max_tokens=160, temperature=0.6
    )
    reply = (reply or "").strip()
    if not reply or reply.lower().startswith("(llm error"):
        reply = (
            "Thanks so much for this! Happy to help — "
            + ("feel free to DM me and I'll share more. " if funnel else "")
        ).strip()
    return reply


async def plan_comment_action(
    persona: Persona,
    comment: InboundComment,
    *,
    now: _dt.datetime | None = None,
    window_minutes: int = 20,
) -> EngagementAction:
    """Decide what to do with one comment on the persona's OWN post."""
    pol = _policy(persona)
    mode = (pol.get("own_comment_reply") or "disabled").lower()
    if mode == "disabled":
        return EngagementAction("skip", comment.id, "", False, "own_comment_reply disabled")

    now = now or _dt.datetime.now(_dt.timezone.utc)
    age_min = (now - comment.created_at).total_seconds() / 60.0
    funnel = bool(pol.get("comment_to_dm_funnel")) and _is_question(comment.text)
    draft = await _draft_reply(persona, comment.text, funnel=funnel, channel="post")

    # auto_after_window: only auto-send once the grace window has elapsed.
    auto = mode == "auto_after_window" and age_min >= window_minutes
    reason = (
        f"auto (age {age_min:.0f}m >= {window_minutes}m)" if auto
        else f"hold (age {age_min:.0f}m < {window_minutes}m)" if mode == "auto_after_window"
        else "draft_then_approve"
    )
    return EngagementAction(
        "comment_reply", comment.id, draft, auto, reason, funnel_to_dm=funnel,
    )


async def plan_dm_action(persona: Persona, dm: InboundDM) -> EngagementAction:
    """Inbound DM — draft a reply, never auto-send (draft_then_approve)."""
    pol = _policy(persona)
    mode = (pol.get("inbound_dm") or "draft_then_approve").lower()
    if mode == "disabled":
        return EngagementAction("skip", dm.id, "", False, "inbound_dm disabled")
    draft = await _draft_reply(persona, dm.text, funnel=False, channel="DM")
    auto = mode == "auto"          # default policy is draft_then_approve => not auto
    return EngagementAction("dm_reply_draft", dm.id, draft, auto, mode)


def assert_no_outbound(persona: Persona) -> None:
    """Hard guard — outbound engagement must stay disabled."""
    pol = _policy(persona)
    if (pol.get("outbound_engagement") or "disabled").lower() != "disabled":
        raise RuntimeError(
            f"persona {persona.persona_id}: outbound_engagement must be 'disabled' "
            "— outbound bots violate platform automation guidelines"
        )


async def process_owned_engagement(
    persona_id: str,
    *,
    comments: list[InboundComment] | None = None,
    dms: list[InboundDM] | None = None,
    send=None,
) -> list[EngagementAction]:
    """Plan (and optionally send) engagement for owned comments + DMs.

    `send(action)` is the transport callback; when None or in dry-run we
    only plan. Auto-send actions are dispatched; draft-only actions are
    returned for the cockpit approval queue.
    """
    persona = load_persona(persona_id)
    assert_no_outbound(persona)
    actions: list[EngagementAction] = []
    for c in comments or []:
        actions.append(await plan_comment_action(persona, c))
    for d in dms or []:
        actions.append(await plan_dm_action(persona, d))

    dry = settings().is_dry_run or send is None
    for a in actions:
        if a.kind == "skip" or not a.auto_send:
            continue
        if dry:
            log.info("influencer.engagement.dry_run", kind=a.kind, target=a.target_id, reason=a.reason)
        else:
            send(a)
            log.info("influencer.engagement.sent", kind=a.kind, target=a.target_id)
    return actions
