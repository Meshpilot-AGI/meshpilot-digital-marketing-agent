"""OpenRouter transport (OpenAI Chat Completions) — the single LLM path for the whole agent.

Migrated from the Anthropic Messages API to **OpenRouter** (2026-08-30). The ReAct loop and every
caller still speak the ANTHROPIC shape (a `system` string, `tool_use`/`tool_result` content blocks,
tool defs as {name,description,input_schema}); this module ADAPTS that to OpenRouter's
OpenAI-compatible `/chat/completions` on the way out and translates the OpenAI response
(`tool_calls`, `finish_reason`) back to the Anthropic shape on the way in — so nothing downstream
changes. Same models (Claude), new provider.

    OPENROUTER_API_KEY   required (sk-or-…)
    AGENT_LLM_MODEL      default model for complete() (internal name or OpenRouter slug)
    AGENT_LLM_BASE       override base URL (default https://openrouter.ai/api/v1)

Internal Claude model names (e.g. `claude-sonnet-5`, `claude-haiku-4-5-20251001`) are normalized to
OpenRouter slugs (`anthropic/claude-sonnet-5`, `anthropic/claude-haiku-4.5`), so callers keep their
existing names. Web search uses OpenRouter's native web plugin (see `complete_web` +
tools.py web_search/web_fetch). Anthropic-only features (prompt caching, output_config.effort) are
not sent.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
import structlog

log = structlog.get_logger(__name__)

_DEFAULT_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "anthropic/claude-sonnet-5"
_RETRYABLE = {429, 500, 502, 503, 529}
_MAX_ATTEMPTS = 3
_APP_HEADERS = {"HTTP-Referer": "https://meshpilot.app", "X-Title": "MeshPilot Agent"}

# Internal (Anthropic-style) model names → OpenRouter slugs. Anything already containing "/" is
# treated as an OpenRouter slug and passed through; unknown bare names get an "anthropic/" prefix.
_MODEL_MAP = {
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4.5",
    "claude-opus-4-8": "anthropic/claude-opus-4.8",
    "claude-opus-5": "anthropic/claude-opus-5",
}


def _key() -> str:
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set — required for the agent LLM (OpenRouter)")
    return key


def _normalize_model(m: str | None) -> str:
    if not m:
        return _DEFAULT_MODEL
    if "/" in m:
        return m
    return _MODEL_MAP.get(m, f"anthropic/{m}")


def _model(model: str | None) -> str:
    return _normalize_model(model or os.environ.get("AGENT_LLM_MODEL") or _DEFAULT_MODEL)


def _flatten_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return str(content)


def _retry_delay(r: httpx.Response, attempt: int) -> float:
    ra = ((getattr(r, "headers", None) or {}).get("retry-after") or "").strip()
    if ra.replace(".", "", 1).isdigit():
        return min(float(ra), 10.0)
    return 0.5 * attempt


# ── content translation ────────────────────────────────────────────────
def _oai_content(content):
    """Anthropic/OpenAI user content (str | block list) → OpenAI content. Handles image blocks both ways."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    out = []
    for b in content:
        if not isinstance(b, dict):
            out.append({"type": "text", "text": str(b)})
            continue
        t = b.get("type")
        if t == "text":
            out.append({"type": "text", "text": b.get("text", "")})
        elif t == "image_url":            # already OpenAI-shaped
            out.append({"type": "image_url", "image_url": b.get("image_url")})
        elif t == "image" and isinstance(b.get("source"), dict):   # Anthropic image → OpenAI image_url
            s = b["source"]
            if s.get("type") == "base64":
                url = f"data:{s.get('media_type', 'image/jpeg')};base64,{s.get('data', '')}"
            else:
                url = s.get("url", "")
            if url:
                out.append({"type": "image_url", "image_url": {"url": url}})
        else:
            out.append({"type": "text", "text": str(b)})
    return out or ""


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    """Anthropic-shaped messages + system string → OpenAI messages (tool_calls / tool role)."""
    oai: list[dict] = []
    if system:
        oai.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "assistant" and isinstance(content, list):
            text_parts, tool_calls = [], []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append({"id": b.get("id"), "type": "function",
                                       "function": {"name": b.get("name"),
                                                    "arguments": json.dumps(b.get("input") or {})}})
            msg: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            oai.append(msg)
        elif role == "user" and isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            for b in content:                                       # one OpenAI tool message per result
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content", "")
                    if isinstance(c, list):
                        c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                    oai.append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": str(c)})
        else:
            oai.append({"role": role, "content": _oai_content(content)})
    return oai


def _to_openai_tools(tools: list[dict] | None) -> list[dict]:
    return [{"type": "function",
             "function": {"name": t.get("name"), "description": t.get("description", ""),
                          "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
            for t in (tools or [])]


_FINISH_MAP = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens",
               "content_filter": "refusal"}


def _from_openai_response(body: dict) -> dict:
    """OpenAI response → Anthropic-shaped {content:[blocks], stop_reason, usage, _id, _citations}."""
    choice = (body.get("choices") or [{}])[0] or {}
    msg = choice.get("message") or {}
    blocks: list[dict] = []
    txt = msg.get("content")
    if isinstance(txt, list):
        txt = "".join(x.get("text", "") for x in txt if isinstance(x, dict))
    if txt:
        blocks.append({"type": "text", "text": txt})
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:  # noqa: BLE001
            args = {}
        blocks.append({"type": "tool_use", "id": tc.get("id"), "name": fn.get("name"), "input": args})
    stop = "tool_use" if msg.get("tool_calls") else _FINISH_MAP.get(choice.get("finish_reason"),
                                                                     choice.get("finish_reason") or "end_turn")
    u = body.get("usage") or {}
    usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
    if u.get("cost") is not None:
        usage["cost"] = u["cost"]
    citations = [a.get("url_citation", {}).get("url") for a in (msg.get("annotations") or [])
                 if isinstance(a, dict)]
    return {"content": blocks, "stop_reason": stop, "usage": usage, "_id": body.get("id"),
            "_citations": [c for c in citations if c]}


async def _send(payload: dict, *, timeout_s: int, client: httpx.AsyncClient | None) -> dict:
    """POST /chat/completions with retry (Retry-After aware); return the response body or raise."""
    base = (os.environ.get("AGENT_LLM_BASE") or _DEFAULT_BASE).rstrip("/")
    headers = {"Authorization": f"Bearer {_key()}", "content-type": "application/json", **_APP_HEADERS}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            r = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
            if r.status_code not in _RETRYABLE or attempt == _MAX_ATTEMPTS:
                break
            await asyncio.sleep(_retry_delay(r, attempt))
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"openrouter chat -> {r.status_code}: {r.text[:200]}")
    return r.json()


async def _meter(model: str, usage: dict, req_id: str | None) -> None:
    """Attribute this call's tokens + cost to the active brand (COST-METER). Never raises."""
    try:
        from glitch_signal.analytics.cost import get_brand, record_usage  # noqa: PLC0415
        from glitch_signal.analytics.cost.pricing import anthropic_cost  # noqa: PLC0415
        cost = usage.get("cost")
        if cost is None:                        # OpenRouter didn't return cost → estimate off the price book
            cost = anthropic_cost(model.split("/")[-1], usage)
        await record_usage(brand_id=get_brand(), vendor="openrouter", operation="chat",
                           model=model, units=usage, cost_usd=cost, request_id=req_id)
    except Exception:  # noqa: BLE001 — metering is best-effort, never breaks the LLM call
        pass


async def _chat(messages: list[dict], *, system: str | None, tools: list[dict] | None,
                model: str | None, max_tokens: int, timeout_s: int,
                client: httpx.AsyncClient | None, plugins: list[dict] | None = None) -> dict:
    payload: dict = {"model": _model(model), "max_tokens": max_tokens,
                     "messages": _to_openai_messages(messages, system),
                     "usage": {"include": True}}
    if tools:
        payload["tools"] = _to_openai_tools(tools)
    if plugins:
        payload["plugins"] = plugins
    body = await _send(payload, timeout_s=timeout_s, client=client)
    resp = _from_openai_response(body)
    await _meter(payload["model"], resp["usage"], resp.get("_id"))
    return resp


def _text(resp: dict) -> str:
    return "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text").strip()


async def complete(prompt: str, *, system: str | None = None, model: str | None = None,
                   timeout_s: int = 90, client: httpx.AsyncClient | None = None,
                   effort: str | None = None) -> str:
    """Single user turn → assistant text. `client` injectable for tests."""
    _ = effort
    resp = await _chat([{"role": "user", "content": prompt}], system=system, tools=None,
                       model=model, max_tokens=2048, timeout_s=timeout_s, client=client)
    return _text(resp)


async def complete_messages(messages: list[dict], *, model: str | None = None,
                            max_tokens: int = 2048, temperature: float = 0.2,
                            timeout_s: int = 90, client: httpx.AsyncClient | None = None,
                            effort: str | None = None) -> str:
    """OpenAI/LiteLLM-style messages (system extracted) → assistant text."""
    _ = (temperature, effort)
    system_parts, conv = [], []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(_flatten_text(m.get("content", "")))
        else:
            conv.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    system = "\n\n".join(p for p in system_parts if p) or None
    resp = await _chat(conv, system=system, tools=None, model=model, max_tokens=max_tokens,
                       timeout_s=timeout_s, client=client)
    return _text(resp)


async def complete_tools(messages: list[dict], *, tools: list[dict], system: str | None = None,
                         model: str | None = None, max_tokens: int = 2048, timeout_s: int = 120,
                         client: httpx.AsyncClient | None = None, effort: str | None = None) -> dict:
    """One native tool-use turn → assistant message {content, stop_reason, usage} (Anthropic shape).

    `tools` are Anthropic tool defs (name/description/input_schema); the caller runs any returned
    tool_use blocks and sends tool_results back next turn.
    """
    _ = effort
    resp = await _chat(messages, system=system, tools=tools, model=model, max_tokens=max_tokens,
                       timeout_s=timeout_s, client=client)
    return {"content": resp["content"], "stop_reason": resp["stop_reason"], "usage": resp["usage"]}


async def complete_web(query: str, *, model: str | None = None, max_results: int = 5,
                       timeout_s: int = 120, client: httpx.AsyncClient | None = None) -> tuple[str, list[str]]:
    """A completion grounded in OpenRouter's NATIVE web plugin. Returns (answer_text, [source urls])."""
    resp = await _chat(
        [{"role": "user", "content": f"Search the web and answer concisely with key facts: {query}\n"
                                     "Cite the sources you used."}],
        system=None, tools=None, model=model, max_tokens=1500, timeout_s=timeout_s, client=client,
        plugins=[{"id": "web", "max_results": max_results}])
    return _text(resp), resp.get("_citations", [])
