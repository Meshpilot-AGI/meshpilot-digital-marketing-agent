"""LLM helper for the influencer engine.

Thin wrapper over the shared Claude API shim (glitch_signal.agent.llm.chat).
Isolated to the influencer package so call sites here keep a stable
`complete(prompt, ...)` signature independent of the shared agent chain.
"""
from __future__ import annotations

import structlog

from glitch_signal.agent import llm as agent_llm

log = structlog.get_logger(__name__)


async def complete(
    prompt: str,
    *,
    tier: str | None = None,
    system: str | None = None,
    max_tokens: int = 400,
    temperature: float = 0.6,
) -> str:
    """Text completion via the shared Claude API. Returns assistant text or ''."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        text = await agent_llm.chat(
            messages,
            tier=(tier or "smart"),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (text or "").strip()
    except Exception as e:  # noqa: BLE001 — callers apply their own deterministic fallback
        log.warning("influencer.llm.failed", error=str(e)[:160])
        return ""
