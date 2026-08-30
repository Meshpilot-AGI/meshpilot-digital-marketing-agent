"""OpenRouter transport (OpenAI Chat Completions) + agent.llm content shim (no network)."""
from __future__ import annotations

from glitch_signal.agent import llm as agent_llm
from glitch_signal.agent.loop import llm as loop_llm


class _Resp:
    def __init__(self, code, payload):
        self.status_code, self._p, self.text = code, payload, str(payload)

    def json(self):
        return self._p


class _Client:
    def __init__(self, resp):
        self._resp, self.posted, self.url = resp, None, None

    async def post(self, url, *, headers=None, json=None):
        self.posted, self.url, self.headers = json, url, headers
        return self._resp


def _ok(text="hi", finish="stop"):
    return _Resp(200, {"id": "gen-1", "choices": [{"message": {"content": text}, "finish_reason": finish}],
                       "usage": {"prompt_tokens": 3, "completion_tokens": 1}})


async def test_system_becomes_a_message_and_user_kept(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    out = await loop_llm.complete_messages(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], client=c)
    assert out == "hi"
    assert c.posted["messages"] == [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    assert "output_config" not in c.posted and "system" not in c.posted   # Anthropic-only, not sent
    assert c.url.endswith("/chat/completions")
    assert c.headers["Authorization"] == "Bearer sk-or-x"


async def test_image_url_passthrough_openai_shape(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]}]
    await loop_llm.complete_messages(msgs, client=c)
    blocks = c.posted["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "describe"}
    assert blocks[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}


async def test_no_sampling_params_sent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    await loop_llm.complete_messages([{"role": "user", "content": "U"}], temperature=0.7, client=c)
    assert "temperature" not in c.posted and "top_p" not in c.posted


async def test_default_model_normalized_to_openrouter_slug(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    await loop_llm.complete_messages([{"role": "user", "content": "U"}], client=c)
    assert c.posted["models"] == ["anthropic/claude-sonnet-5"] and c.posted["max_tokens"] == 2048


def test_model_normalization():
    assert loop_llm._normalize_model("claude-sonnet-5") == "anthropic/claude-sonnet-5"
    assert loop_llm._normalize_model("claude-haiku-4-5-20251001") == "anthropic/claude-haiku-4.5"
    assert loop_llm._normalize_model("anthropic/claude-opus-5") == "anthropic/claude-opus-5"  # slug passthrough
    assert loop_llm._normalize_model("meta-llama/llama-3.3-70b") == "meta-llama/llama-3.3-70b"


def test_retry_delay_honors_retry_after():
    class _R:
        def __init__(self, h):
            self.headers = h
    assert loop_llm._retry_delay(_R({"retry-after": "3"}), 1) == 3.0
    assert loop_llm._retry_delay(_R({"retry-after": "999"}), 1) == 10.0
    assert loop_llm._retry_delay(_R({}), 2) == 1.0


async def test_complete_tools_translates_defs_and_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    # OpenAI-shaped tool_calls response → Anthropic tool_use blocks + stop_reason=tool_use
    resp = _Resp(200, {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "a", "arguments": '{"x":1}'}}]},
        "finish_reason": "tool_calls"}], "usage": {}})
    c = _Client(resp)
    tdefs = [{"name": "a", "description": "A", "input_schema": {"type": "object", "properties": {}}}]
    out = await loop_llm.complete_tools([{"role": "user", "content": "U"}], tools=tdefs, system="S", client=c)
    assert out["stop_reason"] == "tool_use"
    assert out["content"] == [{"type": "tool_use", "id": "call_1", "name": "a", "input": {"x": 1}}]
    # request: Anthropic tool defs → OpenAI function tools; system → a system message
    assert c.posted["tools"][0] == {"type": "function",
                                    "function": {"name": "a", "description": "A",
                                                 "parameters": {"type": "object", "properties": {}}}}
    assert c.posted["models"] == ["anthropic/claude-sonnet-5", "z-ai/glm-5.3", "moonshotai/kimi-k3"]  # complex tier
    assert c.posted["messages"][0] == {"role": "system",
        "content": [{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}]}  # loop prefix cached
    assert "output_config" not in c.posted


async def test_tool_result_message_becomes_tool_role(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    msgs = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "a", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "42"}]},
    ]
    await loop_llm.complete_tools(msgs, tools=[{"name": "a", "description": "", "input_schema": {}}], client=c)
    om = c.posted["messages"]
    assert om[1]["role"] == "assistant" and om[1]["tool_calls"][0]["function"]["name"] == "a"
    assert om[2] == {"role": "tool", "tool_call_id": "t1", "content": "42"}


async def test_multiple_system_messages_joined(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    await loop_llm.complete_messages(
        [{"role": "system", "content": "A"}, {"role": "system", "content": "B"},
         {"role": "user", "content": "U"}], client=c)
    assert c.posted["messages"][0] == {"role": "system", "content": "A\n\nB"}


def test_model_for_claude_defaults_and_env_override(monkeypatch):
    for k in ("AGENT_CONTENT_TEXT_MODEL_CHEAP", "AGENT_CONTENT_TEXT_MODEL_SMART",
              "AGENT_CONTENT_MODEL_CHEAP", "AGENT_CONTENT_MODEL_SMART"):
        monkeypatch.delenv(k, raising=False)
    assert agent_llm.model_for("cheap") == "claude-haiku-4-5-20251001"   # internal name (normalized in transport)
    assert agent_llm.model_for("smart") == "claude-sonnet-5"
    monkeypatch.setenv("AGENT_CONTENT_MODEL_SMART", "claude-opus-5")
    assert agent_llm.model_for("smart") == "claude-opus-5"


async def test_chat_routes_through_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    c = _Client(_ok())
    out = await agent_llm.chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "write X"}],
        tier="smart", client=c)
    assert out == "hi"
    assert c.posted["models"] == ["anthropic/claude-sonnet-5"]   # smart tier → Sonnet 5, normalized
    assert c.posted["messages"] == [{"role": "system", "content": "S"}, {"role": "user", "content": "write X"}]


async def test_complete_with_fallback_returns_sentinel_on_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(agent_llm, "chat", boom)
    out = await agent_llm.complete_with_fallback("hi", tier="smart")
    assert out.startswith("(llm error")
