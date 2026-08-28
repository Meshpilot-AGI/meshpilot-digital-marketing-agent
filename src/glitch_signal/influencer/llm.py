"""LLM helper for the influencer engine — Gemini-first.

The shared agent.llm.complete_with_fallback tries OpenAI (gpt-4o) first,
which on the free/rate-limited tier throttles the whole influencer
engine (discovery hooks, scene prompts, engagement drafts) and silently
returns empty. Gemini Flash is fast, cheap, and reliably available here,
so the influencer modules call THIS helper, which:

  1. tries Gemini (gemini-2.5-flash) directly via litellm, then
  2. falls back to the shared complete_with_fallback chain, then
  3. returns "" so callers apply their own deterministic fallback.

Isolated to the influencer package so we don't change provider order for
every other agent that depends on agent.llm.
"""
from __future__ import annotations

import os

import structlog

from glitch_signal.config import settings

log = structlog.get_logger(__name__)

_GEMINI_MODEL = "gemini/gemini-2.5-flash"


def _gemini_key() -> str:
    """The AI-Studio (GEMINI_API_KEY, 'AIza…') key — NOT settings.google_api_key,
    which on this server is a different OAuth-style token that 'gemini/' rejects."""
    return (os.environ.get("GEMINI_API_KEY") or settings().google_api_key or "").strip()


async def complete(
    prompt: str,
    *,
    tier: str | None = None,   # accepted + ignored (call-site compatibility)
    system: str | None = None,
    max_tokens: int = 400,
    temperature: float = 0.6,
) -> str:
    """Gemini-first text completion. Returns assistant text or ''."""
    s = settings()
    if getattr(s, "platform_llm_via_bedrock", False):
        try:
            import litellm
            msgs: list[dict] = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            resp = await litellm.acompletion(
                model=f"bedrock/converse/{s.bedrock_chat_cheap_model}",
                messages=msgs, max_tokens=max_tokens, temperature=temperature,
                aws_region_name=s.bedrock_region)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception as e:  # noqa: BLE001 — fall through to shared chain
            log.warning("influencer.llm.bedrock_failed", error=str(e)[:160])
    key = _gemini_key()
    if key:
        try:
            import litellm

            messages: list[dict] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            # reasoning_effort='none' disables Gemini 2.5's thinking budget —
            # without it the model spends max_tokens on hidden reasoning and
            # TRUNCATES the actual JSON output (the 2026-06-04 empty-discovery
            # bug). Disabling thinking also makes it faster + cheaper.
            resp = await litellm.acompletion(
                model=_GEMINI_MODEL, messages=messages,
                max_tokens=max_tokens, temperature=temperature, api_key=key,
                reasoning_effort="none",
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception as e:  # noqa: BLE001 — fall through to shared chain
            log.warning("influencer.llm.gemini_failed", error=str(e)[:160])

    # Fallback: the shared OpenAI→Claude→Gemini chain.
    try:
        from glitch_signal.agent.llm import complete_with_fallback
        text = await complete_with_fallback(
            prompt, tier="smart", system=system,
            max_tokens=max_tokens, temperature=temperature,
        )
        if text and not text.lower().startswith("(llm error"):
            return text.strip()
    except Exception as e:  # noqa: BLE001
        log.warning("influencer.llm.fallback_failed", error=str(e)[:160])
    return ""
