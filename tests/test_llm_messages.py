"""complete_messages OpenAI→Anthropic conversion + agent.llm Claude shim (no network)."""
from __future__ import annotations

from glitch_signal.agent import llm as agent_llm
from glitch_signal.agent.loop import llm as loop_llm


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.text = str(payload)

    def json(self):
        return self._p


class _Client:
    def __init__(self, resp):
        self._resp = resp
        self.posted = None

    async def post(self, url, *, headers=None, json=None):
        self.posted = json
        return self._resp


def _ok():
    return _Resp(200, {"content": [{"type": "text", "text": "hi"}]})


async def test_system_extracted_and_user_kept(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _Client(_ok())
    out = await loop_llm.complete_messages(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
        client=c,
    )
    assert out == "hi"
    # system lifted out of messages AND wrapped in a cacheable block (HARDEN)
    assert c.posted["system"] == [
        {"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}
    ]
    assert c.posted["messages"] == [{"role": "user", "content": "U"}]
    assert c.posted["output_config"] == {"effort": "low"}   # thinking suppressed by default


async def test_image_url_data_uri_converted_to_anthropic_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _Client(_ok())
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
    ]}]
    await loop_llm.complete_messages(msgs, client=c)
    blocks = c.posted["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "describe"}
    assert blocks[1] == {"type": "image",
                         "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}


async def test_no_sampling_params_sent(monkeypatch):
    """Current-gen models 400 on temperature/top_p/top_k — we must never send them."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _Client(_ok())
    # caption.py passes temperature=0.7; it must be accepted by the kwarg but not forwarded.
    await loop_llm.complete_messages([{"role": "user", "content": "U"}], temperature=0.7, client=c)
    assert "temperature" not in c.posted
    assert "top_p" not in c.posted and "top_k" not in c.posted


async def test_default_model_and_max_tokens(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _Client(_ok())
    await loop_llm.complete_messages([{"role": "user", "content": "U"}], client=c)
    assert c.posted["model"] == "claude-sonnet-5"     # moved off Haiku 4.5
    assert c.posted["max_tokens"] == 2048             # headroom for thinking + output


async def test_effort_env_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    monkeypatch.setenv("AGENT_LLM_EFFORT", "high")
    c = _Client(_ok())
    await loop_llm.complete_messages([{"role": "user", "content": "U"}], client=c)
    assert c.posted["output_config"] == {"effort": "high"}


async def test_effort_default_skips_output_config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    monkeypatch.delenv("AGENT_LLM_EFFORT", raising=False)
    c = _Client(_ok())
    await loop_llm.complete_messages([{"role": "user", "content": "U"}], effort="default", client=c)
    assert "output_config" not in c.posted


def test_retry_delay_honors_retry_after():
    class _R:
        def __init__(self, h):
            self.headers = h
    assert loop_llm._retry_delay(_R({"retry-after": "3"}), 1) == 3.0     # header wins
    assert loop_llm._retry_delay(_R({"retry-after": "999"}), 1) == 10.0  # capped at 10s
    assert loop_llm._retry_delay(_R({}), 2) == 1.0                       # linear fallback 0.5*2


async def test_complete_tools_payload_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    monkeypatch.delenv("AGENT_LLM_EFFORT", raising=False)
    c = _Client(_Resp(200, {"content": [{"type": "text", "text": "hi"}],
                            "stop_reason": "end_turn", "usage": {}}))
    tdefs = [{"name": "a", "description": "A", "input_schema": {"type": "object"}},
             {"name": "b", "description": "B", "input_schema": {"type": "object"}}]
    out = await loop_llm.complete_tools([{"role": "user", "content": "U"}],
                                        tools=tdefs, system="S", client=c)
    assert out["stop_reason"] == "end_turn"
    # cache breakpoint only on the LAST tool def (tools cache ahead of system)
    assert "cache_control" not in c.posted["tools"][0]
    assert c.posted["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert c.posted["system"][0]["cache_control"] == {"type": "ephemeral"}   # system cached
    assert c.posted["output_config"] == {"effort": "low"}                    # effort default


async def test_multiple_system_messages_joined(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _Client(_ok())
    await loop_llm.complete_messages(
        [{"role": "system", "content": "A"}, {"role": "system", "content": "B"},
         {"role": "user", "content": "U"}],
        client=c,
    )
    assert c.posted["system"] == [
        {"type": "text", "text": "A\n\nB", "cache_control": {"type": "ephemeral"}}
    ]


def test_model_for_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("AGENT_CONTENT_TEXT_MODEL", raising=False)
    monkeypatch.delenv("AGENT_CONTENT_TEXT_MODEL_SMART", raising=False)
    monkeypatch.setattr(agent_llm, "_DEFAULT_TEXT_MODEL", "gemini-3-5-flash")
    assert agent_llm.model_for("cheap") == "gemini-3-5-flash"
    monkeypatch.setenv("AGENT_CONTENT_TEXT_MODEL_SMART", "deepseek-v3")
    assert agent_llm.model_for("smart") == "deepseek-v3"      # per-tier env wins


class _FakeEngine:
    def __init__(self, text="generated"):
        self.text = text
        self.called = None

    async def generate(self, model, prompt, *, images=None, params=None, timeout_s=360):
        self.called = {"model": model, "prompt": prompt, "images": images, "params": params}
        return self.text


async def test_chat_routes_to_muapi_text(monkeypatch):
    monkeypatch.setattr(agent_llm, "_DEFAULT_TEXT_MODEL", "gemini-3-5-flash")
    eng = _FakeEngine("a caption")
    out = await agent_llm.chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "write X"}],
        tier="cheap", engine=eng,
    )
    assert out == "a caption"
    assert eng.called["model"] == "gemini-3-5-flash"          # MUapi text slug, not Claude
    assert eng.called["prompt"] == "write X"
    assert eng.called["params"] == {"system_prompt": "S"}     # system → MUapi system_prompt
    assert eng.called["images"] is None


async def test_complete_with_fallback_returns_sentinel_on_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(agent_llm, "chat", boom)
    out = await agent_llm.complete_with_fallback("hi", tier="smart")
    assert out.startswith("(llm error")
