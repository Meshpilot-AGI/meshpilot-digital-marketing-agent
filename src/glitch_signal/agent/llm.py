"""Text generation for the content pipeline — routed through Claude.

**MUapi stays the IMAGE/VIDEO path** (`media/generation/` + recipes). All content-pipeline **text**
generation (nodes, media captions, sheet_posting, influencer) goes through **Claude** via
`agent/loop/llm.py::complete_messages`, which accepts OpenAI/LiteLLM-style message lists, converts
multimodal `image_url` blocks, passes native `document`/`image` blocks through, and meters to the
per-brand budget (COST-METER).

`tier` selects a Claude model — `cheap` → Haiku 4.5, `smart` → Sonnet 5 (env overrides
`AGENT_CONTENT_MODEL_CHEAP` / `_SMART`, or the legacy per-tier `AGENT_CONTENT_TEXT_MODEL_<TIER>`).
`temperature` is accepted for call-site compatibility but not forwarded (current-gen models 400 on
it). `client` is injectable for tests.
"""
from __future__ import annotations

import os

import structlog

log = structlog.get_logger(__name__)

# tier -> default Claude model.
_TIER_DEFAULTS = {"cheap": "claude-haiku-4-5-20251001", "smart": "claude-sonnet-5"}


def model_for(tier: str = "cheap") -> str:
    """Claude model for a content tier (per-tier env override, else the tier default)."""
    return (os.environ.get(f"AGENT_CONTENT_TEXT_MODEL_{tier.upper()}")
            or os.environ.get(f"AGENT_CONTENT_MODEL_{tier.upper()}")
            or _TIER_DEFAULTS.get(tier, _TIER_DEFAULTS["cheap"]))


async def chat(messages: list[dict], *, tier: str = "cheap", max_tokens: int = 800,
               temperature: float = 0.2, model: str | None = None, client=None) -> str:
    """Run an OpenAI/LiteLLM-style message list through Claude. Returns the generated text.

    `client` (an httpx.AsyncClient) is injectable for tests. `temperature` is accepted for call-site
    compatibility but not forwarded (current-gen models reject sampling params).
    """
    from glitch_signal.agent.loop.llm import complete_messages
    return await complete_messages(messages, model=model or model_for(tier),
                                   max_tokens=max_tokens, temperature=temperature, client=client)


async def complete_with_fallback(prompt: str, *, tier: str = "smart", system: str | None = None,
                                 max_tokens: int = 800, temperature: float = 0.2, **_ignored) -> str:
    """Back-compat wrapper for the influencer engine. Returns text, or '(llm error: …)'."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        return await chat(messages, tier=tier, max_tokens=max_tokens, temperature=temperature)
    except Exception as exc:  # noqa: BLE001 — mirror the old contract: sentinel, don't raise
        log.warning("agent.llm.complete_failed", tier=tier, error=str(exc)[:200])
        return f"(llm error: {str(exc)[:160]})"
