"""LiteLLM-routed model selection.

Tiers and preferred providers (first with a key wins):

  cheap   → OpenAI gpt-4o-mini → Gemini 2.5 Flash
            (novelty scoring, storyboard breakdown — high volume, low depth)

  smart   → OpenAI gpt-4o      → Claude Sonnet 4.6 → Gemini 2.5 Flash
            (script writing, text-post copywriting, carousel slide content,
             ORM classification — instruction-following matters)

  heavy   → Gemini 2.5 Pro     → Vertex 2.5 Pro fallback
            (video QC vision, long-form reasoning)

Why OpenAI first on cheap/smart: gpt-4o family follows explicit "do not"
lists and character-limit constraints more reliably than Gemini Flash in
our testing, which matters a lot for the voice-guard-rails pipeline.

Fallback chain: `pick(tier)` is preserved unchanged so all current call
sites keep their direct-provider behaviour. `complete_with_fallback(...)`
iterates an ordered hop chain with `via=` attribution, advancing on any
failure or empty reply. Pattern mirrors `ads_agent.agent.llm.complete`,
with one deviation: social_agent's existing call sites use `pick()` to
get a model + kwargs and then run their own `litellm.acompletion(...)`,
so we do not retrofit the chain into `pick()` itself — that would
either break the single-choice contract or silently lose fallback.

ClawRouter was removed 2026-07-23; per-workspace OpenRouter keys replace
it (see `docs/plans/2026-07-22-ai-runtime-workspace-binding.md`).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from glitch_signal.config import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelChoice:
    model: str
    kwargs: dict


@dataclass(frozen=True)
class _Hop:
    """One entry in the fallback chain used by `complete_with_fallback`.
    Mirrors `ads_agent.agent.llm._Hop` so the two agents stay
    shape-compatible.

    `via` is the attribution label that surfaces in per-hop log lines
    (currently `direct`) — used for cost-attribution audits."""

    model: str
    kwargs: dict
    via: str


def _build_fallback_chain(tier: str) -> list[_Hop]:
    """Build the ordered hop chain. The direct hop's `kwargs` come
    straight from the existing `pick(tier)` result, so it is the EXACT
    same `ModelChoice` callers would otherwise have received."""
    direct = pick(tier)
    chain: list[_Hop] = [
        _Hop(model=direct.model, kwargs=dict(direct.kwargs), via="direct"),
    ]
    return chain


async def complete_with_fallback(
    prompt: str,
    *,
    tier: str = "cheap",
    system: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> str:
    """Text completion over the ordered hop chain.

    On any failure or empty reply, control advances to the next hop;
    `pick(tier)` remains authoritative as the direct-provider hop.

    Callers migrate from `pick(tier)` + their own `litellm.acompletion`
    call to this helper. Existing callers that still call `pick(tier)`
    directly continue to behave exactly as before — opt-in at the call
    site. Returns the assistant text or an error-shaped string mirroring
    `ads_agent.agent.llm.complete`."""
    import litellm

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_err: Exception | None = None
    for hop in _build_fallback_chain(tier):
        try:
            resp = await litellm.acompletion(
                model=hop.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **hop.kwargs,
            )
            choice = resp.choices[0]
            text = choice.message.content or ""
            finish = getattr(choice, "finish_reason", "unknown")
            log.info(
                "LLM %s via=%s finish_reason=%s len=%d",
                hop.model, hop.via, finish, len(text),
            )
            if text.strip():
                return text
        except Exception as e:  # noqa: BLE001 — every error funnels to fallback
            last_err = e
            log.warning(
                "LLM %s via=%s failed: %s",
                hop.model, hop.via, str(e)[:200],
            )
            continue

    log.error("all LLM providers failed for tier=%s", tier)
    return f"(LLM error across all providers: {last_err})"


def pick(tier: str = "cheap") -> ModelChoice:
    s = settings()

    # All internal LLM -> Amazon Bedrock when enabled (AWS credits).
    if getattr(s, "platform_llm_via_bedrock", False):
        mid = (s.bedrock_chat_premium_model if tier in ("smart", "heavy")
               else s.bedrock_chat_cheap_model)
        return ModelChoice(model=f"bedrock/converse/{mid}",
                           kwargs={"aws_region_name": s.bedrock_region})

    if tier == "smart":
        if s.openai_api_key:
            return ModelChoice(
                model=s.openai_smart_model,   # e.g. "gpt-4o"
                kwargs={"api_key": s.openai_api_key},
            )
        if s.anthropic_api_key:
            return ModelChoice(
                model="claude-sonnet-4-6",
                kwargs={"api_key": s.anthropic_api_key},
            )
        # Fall through to Gemini Flash below — not ideal for smart tier,
        # but keeps the graph working when nothing else is configured.

    if tier == "heavy":
        if s.vertex_project:
            return ModelChoice(
                model="vertex_ai/gemini-2.5-pro",
                kwargs={
                    "vertex_project": s.vertex_project,
                    "vertex_location": s.vertex_location,
                },
            )
        return ModelChoice(
            model="gemini/gemini-2.5-pro",
            kwargs={"api_key": s.google_api_key},
        )

    # cheap (default) — and smart fallback
    if s.openai_api_key:
        return ModelChoice(
            model=s.openai_cheap_model,      # e.g. "gpt-4o-mini"
            kwargs={"api_key": s.openai_api_key},
        )
    if s.vertex_project:
        return ModelChoice(
            model="vertex_ai/gemini-2.5-flash",
            kwargs={
                "vertex_project": s.vertex_project,
                "vertex_location": s.vertex_location,
            },
        )
    return ModelChoice(
        model="gemini/gemini-2.5-flash",
        kwargs={"api_key": s.google_api_key},
    )
