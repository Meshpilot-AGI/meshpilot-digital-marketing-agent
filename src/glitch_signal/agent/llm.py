"""Text generation for the content pipeline — routed through MUapi.

Claude is reserved for the agent BRAIN runtime (the ReAct loop + curator) in
`agent/loop/llm.py`. Content-pipeline text/caption generation (nodes, media, sheet_posting,
influencer) goes through **MUapi's text-to-text gateway** instead — the same `MUAPI_API_KEY`
that powers image/video, no separate LLM provider. The one exception is vision QC
(`agent/nodes/quality_check.py`), which calls Claude vision directly because MUapi text-to-text
can't analyze video frames.

Call sites pass OpenAI/LiteLLM-style message lists to `chat()`; we flatten them to MUapi's
prompt + `system_prompt` contract. `tier` selects a MUapi text model (all default to one capable,
cheap model; override globally via `AGENT_CONTENT_TEXT_MODEL` or per-tier via
`AGENT_CONTENT_TEXT_MODEL_<TIER>`). `max_tokens`/`temperature` are accepted for call-site
compatibility but not forwarded — MUapi text models use their own defaults, matching the media
composer contract (`media/generation/compose.py`).
"""
from __future__ import annotations

import os

import structlog

from glitch_signal.media.generation.engines.muapi import MuapiEngine

log = structlog.get_logger(__name__)

# One capable, cheap MUapi text-to-text slug by default (same family the media composer uses).
_DEFAULT_TEXT_MODEL = (
    os.environ.get("AGENT_CONTENT_TEXT_MODEL")
    or os.environ.get("MEDIA_TEXT_MODEL", "gemini-3-5-flash")
)


def model_for(tier: str = "cheap") -> str:
    """MUapi text model for a tier (per-tier env override, else the global default)."""
    return os.environ.get(f"AGENT_CONTENT_TEXT_MODEL_{tier.upper()}") or _DEFAULT_TEXT_MODEL


def _flatten(messages: list[dict]) -> tuple[str | None, str, list[str]]:
    """Collapse an OpenAI-style message list into (system, prompt, image_urls) for MUapi."""
    system_parts: list[str] = []
    user_parts: list[str] = []
    images: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            texts = []
            for b in content:
                if not isinstance(b, dict):
                    texts.append(str(b))
                elif b.get("type") == "text":
                    texts.append(b.get("text", ""))
                elif b.get("type") == "image_url":
                    iu = b.get("image_url")
                    url = iu.get("url", "") if isinstance(iu, dict) else (iu or "")
                    if url:
                        images.append(url)
            content = "\n".join(t for t in texts if t)
        (system_parts if role == "system" else user_parts).append(content)
    system = "\n\n".join(p for p in system_parts if p) or None
    prompt = "\n\n".join(p for p in user_parts if p)
    return system, prompt, images


async def chat(messages: list[dict], *, tier: str = "cheap", max_tokens: int = 800,
               temperature: float = 0.2, model: str | None = None, engine=None) -> str:
    """Run an OpenAI/LiteLLM-style message list through MUapi text. Returns the generated text.

    `engine` is injectable for tests. `max_tokens`/`temperature` are accepted for call-site
    compatibility but not forwarded (MUapi text models use their own defaults).
    """
    system, prompt, images = _flatten(messages)
    params = {"system_prompt": system} if system else {}
    eng = engine or MuapiEngine()
    text = await eng.generate(model or model_for(tier), prompt,
                              images=images or None, params=params, timeout_s=120)
    return (text or "").strip()


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
