"""LLM completion for the agent loop — Anthropic Claude Messages API (synchronous).

The loop needs many quick round-trips. Claude's Messages API is synchronous and fast, so
the loop uses it directly. Default model is a small/fast Claude (good for JSON ReAct steps),
overridable per-env. Injectable via the `run(llm=...)` param and the `client` arg for tests.

    ANTHROPIC_API_KEY    required — an INFERENCE key (sk-ant-api…, workspace/personal/service
                         account). NOT an Admin key (sk-ant-admin…), which cannot call /messages.
    AGENT_LLM_MODEL      override (default claude-haiku-4-5-20251001)
    AGENT_LLM_BASE       override base URL (default https://api.anthropic.com)
"""
from __future__ import annotations

import os

import httpx

_DEFAULT_BASE = "https://api.anthropic.com"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_ANTHROPIC_VERSION = "2023-06-01"


def _key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — required for the agent loop LLM")
    if key.startswith("sk-ant-admin"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is an Admin key (sk-ant-admin…) — it cannot call /v1/messages. "
            "Use an inference key (sk-ant-api…) created in the Console for the workspace."
        )
    return key


async def complete(prompt: str, *, system: str | None = None, model: str | None = None,
                   timeout_s: int = 90, client: httpx.AsyncClient | None = None) -> str:
    """Return Claude's completion for a single user turn. `client` injectable for tests."""
    base = (os.environ.get("AGENT_LLM_BASE") or _DEFAULT_BASE).rstrip("/")
    payload: dict = {
        "model": model or os.environ.get("AGENT_LLM_MODEL", _DEFAULT_MODEL),
        "max_tokens": 800,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": _key(),
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await client.post(f"{base}/v1/messages", headers=headers, json=payload)
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"anthropic messages -> {r.status_code}: {r.text[:200]}")
    blocks = r.json().get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return text.strip()
