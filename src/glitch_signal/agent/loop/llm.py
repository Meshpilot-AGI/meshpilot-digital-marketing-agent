"""Claude Messages API transport (synchronous) — the single LLM path for the whole agent.

Used by the ReAct loop (`complete`) and, via `agent/llm.py`'s `chat()` shim, by the legacy
content pipeline (nodes, media, influencer). `complete_messages` accepts an OpenAI/LiteLLM-style
message list — including multimodal `image_url` blocks — and converts it to Anthropic's format,
so call sites migrating off LiteLLM keep their message shapes.

    ANTHROPIC_API_KEY    required — an INFERENCE key (sk-ant-api…). NOT an Admin key.
    AGENT_LLM_MODEL      default model for `complete()` (default claude-haiku-4-5-20251001)
    AGENT_LLM_BASE       override base URL (default https://api.anthropic.com)
"""
from __future__ import annotations

import asyncio
import os

import httpx

_DEFAULT_BASE = "https://api.anthropic.com"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_ANTHROPIC_VERSION = "2023-06-01"
_RETRYABLE = {429, 500, 502, 503, 529}  # transient — retry with backoff
_MAX_ATTEMPTS = 3


def _key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — required for the agent LLM")
    if key.startswith("sk-ant-admin"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is an Admin key (sk-ant-admin…) — it cannot call /v1/messages. "
            "Use an inference key (sk-ant-api…) created in the Console for the workspace."
        )
    return key


def _content_to_anthropic(content):
    """Convert one message's content (str or OpenAI-style block list) to Anthropic content."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    blocks = []
    for b in content:
        if not isinstance(b, dict):
            blocks.append({"type": "text", "text": str(b)})
            continue
        t = b.get("type")
        if t == "text":
            blocks.append({"type": "text", "text": b.get("text", "")})
        elif t == "image_url":
            url = (b.get("image_url") or {}).get("url", "") if isinstance(b.get("image_url"), dict) else b.get("image_url", "")
            if isinstance(url, str) and url.startswith("data:"):
                header, _, data = url.partition(",")
                media_type = header[5:].split(";")[0] or "image/jpeg"  # strip 'data:' + ';base64'
                blocks.append({"type": "image",
                               "source": {"type": "base64", "media_type": media_type, "data": data}})
            elif url:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        else:
            blocks.append({"type": "text", "text": str(b)})
    return blocks


def _flatten_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content)


async def _post(messages: list[dict], *, system: str | None, model: str | None,
                max_tokens: int, temperature: float, timeout_s: int,
                client: httpx.AsyncClient | None) -> str:
    base = (os.environ.get("AGENT_LLM_BASE") or _DEFAULT_BASE).rstrip("/")
    payload: dict = {
        "model": model or os.environ.get("AGENT_LLM_MODEL", _DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
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
        r = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            r = await client.post(f"{base}/v1/messages", headers=headers, json=payload)
            if r.status_code not in _RETRYABLE or attempt == _MAX_ATTEMPTS:
                break
            await asyncio.sleep(0.5 * attempt)  # brief linear backoff on transient 5xx/429
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"anthropic messages -> {r.status_code}: {r.text[:200]}")
    body = r.json()
    await _meter(payload["model"], body)
    blocks = body.get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


async def _meter(model: str, body: dict) -> None:
    """Attribute this call's tokens + cost to the active brand (COST-METER). Never raises."""
    try:
        from glitch_signal.analytics.cost import get_brand, record_usage  # noqa: PLC0415
        from glitch_signal.analytics.cost.pricing import anthropic_cost  # noqa: PLC0415

        usage = body.get("usage") or {}
        await record_usage(
            brand_id=get_brand(),
            vendor="anthropic",
            operation="chat",
            model=model,
            units=usage,
            cost_usd=anthropic_cost(model, usage),
            request_id=body.get("id"),
        )
    except Exception:  # noqa: BLE001 — metering is best-effort, never breaks the LLM call
        pass


async def complete(prompt: str, *, system: str | None = None, model: str | None = None,
                   timeout_s: int = 90, client: httpx.AsyncClient | None = None) -> str:
    """Single user turn → assistant text. `client` injectable for tests."""
    return await _post([{"role": "user", "content": prompt}], system=system, model=model,
                       max_tokens=800, temperature=0.2, timeout_s=timeout_s, client=client)


async def complete_messages(messages: list[dict], *, model: str | None = None,
                            max_tokens: int = 800, temperature: float = 0.2,
                            timeout_s: int = 90, client: httpx.AsyncClient | None = None) -> str:
    """OpenAI/LiteLLM-style messages (system extracted, multimodal converted) → assistant text."""
    system_parts: list[str] = []
    conv: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(_flatten_text(m.get("content", "")))
        else:
            conv.append({"role": m.get("role", "user"),
                         "content": _content_to_anthropic(m.get("content", ""))})
    system = "\n\n".join(p for p in system_parts if p) or None
    return await _post(conv, system=system, model=model, max_tokens=max_tokens,
                       temperature=temperature, timeout_s=timeout_s, client=client)
