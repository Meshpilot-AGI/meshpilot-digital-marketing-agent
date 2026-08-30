"""Claude Messages API transport (synchronous) — the single LLM path for the whole agent.

Used by the ReAct loop (`complete`) and, via `agent/llm.py`'s `chat()` shim, by the legacy
content pipeline (nodes, media, influencer). `complete_messages` accepts an OpenAI/LiteLLM-style
message list — including multimodal `image_url` blocks — and converts it to Anthropic's format,
so call sites migrating off LiteLLM keep their message shapes.

    ANTHROPIC_API_KEY    required — an INFERENCE key (sk-ant-api…). NOT an Admin key.
    AGENT_LLM_MODEL      default model for `complete()` (default claude-sonnet-5)
    AGENT_LLM_BASE       override base URL (default https://api.anthropic.com)
    AGENT_LLM_EFFORT     adaptive-thinking depth (default "low" — suppresses the thinking
                         block for the JSON loop; "default" skips the param)

Current-generation Claude models (Sonnet 5 / Opus 5 / 4.7+) REJECT sampling params
(`temperature`/`top_p`/`top_k`) with a 400, so we never send them — steer via the prompt.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import structlog

log = structlog.get_logger(__name__)

_DEFAULT_BASE = "https://api.anthropic.com"
_DEFAULT_MODEL = "claude-sonnet-5"
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


def _retry_delay(r: httpx.Response, attempt: int) -> float:
    """Honor a numeric Retry-After header (capped); else brief linear backoff."""
    ra = ((getattr(r, "headers", None) or {}).get("retry-after") or "").strip()
    if ra.replace(".", "", 1).isdigit():
        return min(float(ra), 10.0)
    return 0.5 * attempt


async def _post(messages: list[dict], *, system: str | None, model: str | None,
                max_tokens: int, temperature: float, timeout_s: int,
                client: httpx.AsyncClient | None, effort: str | None = None) -> str:
    base = (os.environ.get("AGENT_LLM_BASE") or _DEFAULT_BASE).rstrip("/")
    payload: dict = {
        "model": model or os.environ.get("AGENT_LLM_MODEL", _DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "messages": messages,
    }
    # NB: `temperature` (and top_p/top_k) are intentionally NOT sent — current-gen models
    # (Sonnet 5 / Opus 5 / 4.7+) 400 on them. The kwarg is kept for caller back-compat only.
    _ = temperature
    # Adaptive-thinking depth. `low` suppresses the thinking block entirely (verified) → the
    # loop gets clean JSON, ~half the output tokens. `default` skips the param (model default).
    eff = (effort if effort is not None else os.environ.get("AGENT_LLM_EFFORT", "low")).strip()
    if eff and eff != "default":
        payload["output_config"] = {"effort": eff}
    if system:
        # Cache the (stable) system prefix — our SOUL/tools prompt is byte-identical across
        # every step/run/brand, so this is the biggest cost+latency lever. GA on 2023-06-01,
        # no beta header. Caches on Sonnet 5 (min 1024 tok); a small system just won't cache.
        payload["system"] = [{"type": "text", "text": system,
                              "cache_control": {"type": "ephemeral"}}]
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
            await asyncio.sleep(_retry_delay(r, attempt))  # Retry-After, else linear backoff
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"anthropic messages -> {r.status_code}: {r.text[:200]}")
    body = r.json()
    await _meter(payload["model"], body)
    stop = body.get("stop_reason")
    blocks = body.get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    # Surface non-happy terminal states instead of silently returning "" (the ReAct loop
    # would otherwise just log an unparseable step with no idea why).
    if stop == "max_tokens":
        log.warning("agent.llm.truncated", model=payload["model"], max_tokens=max_tokens)
    elif stop == "refusal":
        log.warning("agent.llm.refusal", model=payload["model"])
    elif not text:
        log.warning("agent.llm.empty_text", stop_reason=stop,
                    blocks=[b.get("type") for b in blocks])
    return text


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
                   timeout_s: int = 90, client: httpx.AsyncClient | None = None,
                   effort: str | None = None) -> str:
    """Single user turn → assistant text. `client` injectable for tests."""
    return await _post([{"role": "user", "content": prompt}], system=system, model=model,
                       max_tokens=2048, temperature=0.2, timeout_s=timeout_s, client=client,
                       effort=effort)


async def complete_messages(messages: list[dict], *, model: str | None = None,
                            max_tokens: int = 2048, temperature: float = 0.2,
                            timeout_s: int = 90, client: httpx.AsyncClient | None = None,
                            effort: str | None = None) -> str:
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
                       temperature=temperature, timeout_s=timeout_s, client=client, effort=effort)
