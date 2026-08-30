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
# content tier -> ROUTER tier (quality-first list + native fallback). An explicit env override
# (AGENT_CONTENT_[TEXT_]MODEL_<TIER>) still pins a single model and skips the router.
_ROUTER_TIER = {"cheap": "simple", "smart": "complex"}


def model_for(tier: str = "cheap") -> str:
    """Claude model for a content tier (per-tier env override, else the tier default)."""
    return (os.environ.get(f"AGENT_CONTENT_TEXT_MODEL_{tier.upper()}")
            or os.environ.get(f"AGENT_CONTENT_MODEL_{tier.upper()}")
            or _TIER_DEFAULTS.get(tier, _TIER_DEFAULTS["cheap"]))


def _route(tier: str) -> tuple[str | None, str | None]:
    """(model, router_tier): an explicit env override pins a model; otherwise route through the
    model router's tier so content generation gets quality-first selection + native fallback."""
    override = (os.environ.get(f"AGENT_CONTENT_TEXT_MODEL_{tier.upper()}")
                or os.environ.get(f"AGENT_CONTENT_MODEL_{tier.upper()}"))
    if override:
        return override, None
    return None, _ROUTER_TIER.get(tier, "moderate")


async def chat(messages: list[dict], *, tier: str = "cheap", max_tokens: int = 800,
               temperature: float = 0.2, model: str | None = None, client=None) -> str:
    """Run an OpenAI/LiteLLM-style message list through Claude. Returns the generated text.

    `client` (an httpx.AsyncClient) is injectable for tests. `temperature` is accepted for call-site
    compatibility but not forwarded (current-gen models reject sampling params).
    """
    from glitch_signal.agent.loop.llm import complete_messages
    if model:                                    # caller pinned a model → use it verbatim
        routed_model, routed_tier = model, None
    else:
        routed_model, routed_tier = _route(tier)
    return await complete_messages(messages, model=routed_model, tier=routed_tier,
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
