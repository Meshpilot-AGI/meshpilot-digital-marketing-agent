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
        elif t in ("document", "image") and "source" in b:
            blocks.append(b)  # already an Anthropic-native block (e.g. Files API document) — pass through
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


def _model(model: str | None) -> str:
    return model or os.environ.get("AGENT_LLM_MODEL", _DEFAULT_MODEL)


def _apply_effort(payload: dict, effort: str | None) -> None:
    # Adaptive-thinking depth (`output_config.effort`). `low` suppresses the thinking block →
    # clean output, ~half the tokens. `default` skips the param (model default).
    # NB: effort is a Claude-5-family (adaptive-thinking) param — **Haiku 4.5 rejects it (400)**,
    # so never send it for Haiku (the content pipeline's `cheap` tier).
    if "haiku" in (payload.get("model") or "").lower():
        return
    eff = (effort if effort is not None else os.environ.get("AGENT_LLM_EFFORT", "low")).strip()
    if eff and eff != "default":
        payload["output_config"] = {"effort": eff}


def _cache_block(text: str) -> list[dict]:
    # Cache the (stable) system prefix — biggest cost+latency lever. GA on 2023-06-01, no beta
    # header. Caches on Sonnet 5 (min 1024 tok); a small system just won't cache.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


async def _send(payload: dict, *, timeout_s: int, client: httpx.AsyncClient | None) -> dict:
    """POST /v1/messages with retry (Retry-After aware); return the response body or raise."""
    base = (os.environ.get("AGENT_LLM_BASE") or _DEFAULT_BASE).rstrip("/")
    headers = {"x-api-key": _key(), "anthropic-version": _ANTHROPIC_VERSION,
               "content-type": "application/json"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            r = await client.post(f"{base}/v1/messages", headers=headers, json=payload)
            if r.status_code not in _RETRYABLE or attempt == _MAX_ATTEMPTS:
                break
            await asyncio.sleep(_retry_delay(r, attempt))
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"anthropic messages -> {r.status_code}: {r.text[:200]}")
    return r.json()


async def _post(messages: list[dict], *, system: str | None, model: str | None,
                max_tokens: int, temperature: float, timeout_s: int,
                client: httpx.AsyncClient | None, effort: str | None = None) -> str:
    # `temperature`/top_p/top_k are NOT sent — current-gen models 400 on them (kwarg kept for
    # caller back-compat only).
    _ = temperature
    payload: dict = {"model": _model(model), "max_tokens": max_tokens, "messages": messages}
    _apply_effort(payload, effort)
    if system:
        payload["system"] = _cache_block(system)
    body = await _send(payload, timeout_s=timeout_s, client=client)
    await _meter(payload["model"], body)
    stop = body.get("stop_reason")
    blocks = body.get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
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


async def complete_tools(messages: list[dict], *, tools: list[dict], system: str | None = None,
                         model: str | None = None, max_tokens: int = 2048, timeout_s: int = 120,
                         client: httpx.AsyncClient | None = None, effort: str | None = None) -> dict:
    """One native tool-use turn. Returns the assistant message {content, stop_reason, usage}.

    `tools` are Anthropic tool defs (name/description/input_schema[/strict]); the LAST tool gets
    a cache_control breakpoint so the (stable) tool block caches ahead of the system block.
    The caller runs any tool_use blocks and sends the tool_results back on the next turn.
    """
    payload: dict = {"model": _model(model), "max_tokens": max_tokens, "messages": messages}
    _apply_effort(payload, effort)
    if tools:
        tt = [dict(t) for t in tools]
        tt[-1] = {**tt[-1], "cache_control": {"type": "ephemeral"}}
        payload["tools"] = tt
    if system:
        payload["system"] = _cache_block(system)
    body = await _send(payload, timeout_s=timeout_s, client=client)
    await _meter(payload["model"], body)
    return {"content": body.get("content", []),
            "stop_reason": body.get("stop_reason"),
            "usage": body.get("usage", {})}
