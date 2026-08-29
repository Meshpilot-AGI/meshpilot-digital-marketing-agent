"""LLM completion for the agent loop — muapi text model (any-model, one key).

muapi's text endpoint is a simple prompt→completion (not native tool-calling), so the
loop drives tools via a ReAct/JSON protocol over this. Injectable for tests.
"""
from __future__ import annotations

import os

from glitch_signal.media.generation.engines.muapi import MuapiEngine

_DEFAULT_MODEL = os.environ.get("AGENT_LLM_MODEL", os.environ.get("MEDIA_TEXT_MODEL", "gemini-3-5-flash"))


async def complete(prompt: str, *, system: str | None = None, model: str | None = None,
                   timeout_s: int = 120) -> str:
    """Return the model's text completion for `prompt` (+ optional system prompt)."""
    eng = MuapiEngine()
    params = {"system_prompt": system} if system else {}
    return (await eng.generate(model or _DEFAULT_MODEL, prompt, params=params, timeout_s=timeout_s)).strip()
