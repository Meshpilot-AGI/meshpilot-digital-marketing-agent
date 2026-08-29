"""LLM composer for prompt-authored recipe phases (MEDIA-2).

Recipes whose phases carry `prompt_mode: "llm"` (or an `op: "llm"` step) don't
ship a fixed prompt — they ship an *instruction* the runner renders and hands to
a composer, which authors the concrete prompt the media model receives.

We route text generation through **muapi itself** (it's a unified gateway with
73+ text-to-text models — Gemini/Claude/GPT/DeepSeek). A muapi text model uses
the exact same submit→poll contract as the image/video models and returns the
generated text in `outputs[0]`, so the same `MuapiEngine` drives it — one key
(`MUAPI_API_KEY`) powers media *and* text, no separate LLM key.

The runner injects this via `compose=`; a fully-templated recipe never calls it.
"""
from __future__ import annotations

import os
from typing import Any

from glitch_signal.media.generation.engines.base import Engine, EngineError
from glitch_signal.media.generation.engines.muapi import MuapiEngine

_SYSTEM = (
    "You are a senior creative director writing prompts for image and video "
    "generation models. Output ONLY the final prompt text the model should "
    "receive — no preamble, no explanation, no markdown, no surrounding quotes."
)

# Cheap, fast, capable default; override per-deploy. Any muapi Text-to-Text slug works.
_TEXT_MODEL = os.environ.get("MEDIA_TEXT_MODEL", "gemini-3-5-flash")


async def llm_compose(
    instruction: str,
    variables: dict[str, Any],
    *,
    engine: Engine | None = None,
) -> str:
    """Author a media-model prompt from a rendered recipe instruction, via muapi.

    `variables` (resolved recipe inputs/outputs) is available for future brand-voice
    injection; today the instruction already carries the brand style the recipe
    declared. `engine` is injectable for tests. Raises EngineError on empty output
    so we never submit a blank prompt to a generation model.
    """
    eng = engine or MuapiEngine()
    text = (
        await eng.generate(
            _TEXT_MODEL,
            instruction,
            params={"system_prompt": _SYSTEM},
            timeout_s=120,
        )
    ).strip()
    if not text:
        raise EngineError(f"LLM composer ({_TEXT_MODEL}) returned empty text")
    return text
