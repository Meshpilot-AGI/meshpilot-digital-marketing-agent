"""AGENT-LOOP — native tool-use loop mechanics with a scripted model + fake tools (no network)."""
from __future__ import annotations

import pytest

from glitch_signal.agent.loop import run


def _use(name, inp, tid="t1"):
    """A scripted assistant turn that calls one tool."""
    return {"stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}


def _done(text):
    """A scripted assistant turn that finishes with plain text (no tool call)."""
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


class ScriptedLLM:
    """Injected in place of complete_tools: (messages, *, tools, system) -> response dict."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, messages, *, tools=None, system=None):
        self.calls.append(list(messages))   # snapshot: the loop mutates `messages` after the call
        return self.responses.pop(0) if self.responses else _done("(out of script)")


class FakeExec:
    def __init__(self):
        self.calls = []

    async def __call__(self, tool, args, brand_id):
        self.calls.append((tool, args))
        return {
            "recall": "[]",
            "generate_media": "generated image via muapi-logo-creator: https://cdn/x.png",
            "remember": "remembered",
        }.get(tool, f"ran {tool}")


# ── loop ──────────────────────────────────────────────────────────────
async def test_loop_runs_actions_and_writes_episode():
    llm = ScriptedLLM([
        _use("generate_media", {"recipe": "muapi-logo-creator", "inputs": {}}),
        _done("made a logo"),
    ])
    ex = FakeExec()
    res = await run("glitch_executor", "make a logo", llm=llm, execute=ex, scope="full")
    assert res["final"] == "made a logo" and res["steps"] == 2
    called = [c[0] for c in ex.calls]
    assert called[0] == "recall"          # seed recall before the loop
    assert "generate_media" in called
    assert called[-1] == "remember"       # episode write at the end


async def test_loop_denies_publish():
    llm = ScriptedLLM([
        _use("publish", {"platform": "x", "text": "hi"}),
        _done("stopped — publishing is off"),
    ])
    ex = FakeExec()
    res = await run("glitch_executor", "post to X", llm=llm, execute=ex)
    assert res["transcript"][0]["observation"].startswith("DENIED")
    assert not any(c[0] == "publish" for c in ex.calls)  # never executed


async def test_loop_enforces_media_budget(monkeypatch):
    # 3 media-gen attempts, then finish; policy caps at 2 → 3rd is DENIED, never executed.
    from glitch_signal.agent.loop import policy
    monkeypatch.setattr(policy, "from_config", lambda: policy.Policy(max_media_per_run=2))
    gm = {"recipe": "muapi-logo-creator", "inputs": {}}
    llm = ScriptedLLM([_use("generate_media", gm, "a"), _use("generate_media", gm, "b"),
                       _use("generate_media", gm, "c"), _done("done")])
    ex = FakeExec()
    res = await run("b", "make logos", llm=llm, execute=ex, max_steps=6, scope="full")
    gen_calls = [c for c in ex.calls if c[0] == "generate_media"]
    assert len(gen_calls) == 2                                  # only 2 actually executed
    assert res["transcript"][2]["observation"].startswith("DENIED")  # 3rd blocked by budget


async def test_loop_handles_parallel_tool_uses_in_one_turn():
    # The model returns two tool_use blocks at once → both run, both results returned together.
    llm = ScriptedLLM([
        {"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "a", "name": "recall", "input": {"query": "x"}},
            {"type": "tool_use", "id": "b", "name": "list_recipes", "input": {}},
        ]},
        _done("ok"),
    ])
    ex = FakeExec()
    res = await run("b", "g", llm=llm, execute=ex, scope="full")
    assert res["final"] == "ok"
    names = [c[0] for c in ex.calls]
    assert "recall" in names and "list_recipes" in names
    # the tool_results were sent back in ONE user message (parallel), matched by id
    tool_result_msg = llm.calls[1][-1]
    assert tool_result_msg["role"] == "user"
    got = [b["tool_use_id"] for b in tool_result_msg["content"] if b["type"] == "tool_result"]
    assert set(got) == {"a", "b"}


async def test_loop_stops_at_max_steps():
    llm = ScriptedLLM([_use("recall", {"query": "x"}, f"t{i}") for i in range(10)])  # never finishes
    ex = FakeExec()
    res = await run("b", "g", llm=llm, execute=ex, max_steps=3)
    assert res["final"] is None and res["steps"] == 3
    assert ex.calls[-1][0] == "remember"  # episode still written on timeout


async def test_loop_resumes_on_pause_turn():
    # A paused server-tool turn is re-sent (resumed), not treated as the final answer.
    llm = ScriptedLLM([
        {"stop_reason": "pause_turn", "content": [{"type": "text", "text": "searching…"}]},
        _done("found it"),
    ])
    ex = FakeExec()
    res = await run("b", "g", llm=llm, execute=ex)
    assert res["final"] == "found it" and res["steps"] == 2


def test_server_tool_defs_gating(monkeypatch):
    from glitch_signal.agent.loop import tools
    for k in ("AGENT_WEB_SEARCH_ENABLED", "AGENT_WEB_FETCH_ENABLED", "AGENT_WEB_SEARCH_MAX_USES",
              "AGENT_WEB_BLOCKED_DOMAINS", "AGENT_WEB_SEARCH_TAG"):
        monkeypatch.delenv(k, raising=False)
    defs = tools.server_tool_defs()                        # both on by default (standard org)
    assert {t["name"] for t in defs} == {"web_search", "web_fetch"}
    ws = next(t for t in defs if t["name"] == "web_search")
    assert ws["type"] == "web_search_20250305" and ws["max_uses"] == 3  # basic tag (dynamic opt-in)
    monkeypatch.setenv("AGENT_WEB_FETCH_ENABLED", "false")  # gate fetch off
    assert {t["name"] for t in tools.server_tool_defs()} == {"web_search"}
    monkeypatch.setenv("AGENT_WEB_FETCH_ENABLED", "true")
    monkeypatch.setenv("AGENT_WEB_SEARCH_ENABLED", "false")  # gate search off
    assert {t["name"] for t in tools.server_tool_defs()} == {"web_fetch"}
    monkeypatch.setenv("AGENT_WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENT_WEB_BLOCKED_DOMAINS", "evil.com, spam.io")
    ws = next(t for t in tools.server_tool_defs() if t["name"] == "web_search")
    assert ws["blocked_domains"] == ["evil.com", "spam.io"]


# ── NVIDIA chat llm.complete (injected fake httpx client, no network) ──
class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeHTTPX:
    def __init__(self, resp):
        self._resp = resp
        self.posted = None

    async def post(self, url, *, headers=None, json=None):
        self.posted = {"url": url, "headers": headers, "json": json}
        return self._resp


async def test_llm_complete_parses_text_blocks(monkeypatch):
    from glitch_signal.agent.loop import llm as agent_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    fake = _FakeHTTPX(_FakeResp(200, {"content": [{"type": "text", "text": '{"final":"ok"}'}]}))
    out = await agent_llm.complete("hi", system="sys", client=fake)
    assert out == '{"final":"ok"}'
    assert fake.posted["url"].endswith("/v1/messages")
    # system is top-level and wrapped in a cacheable block (HARDEN — prompt caching)
    assert fake.posted["json"]["system"] == [
        {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    ]
    assert fake.posted["json"]["messages"][0] == {"role": "user", "content": "hi"}
    assert fake.posted["headers"]["x-api-key"] == "sk-ant-api-test"
    assert fake.posted["headers"]["anthropic-version"]


async def test_llm_complete_rejects_admin_key(monkeypatch):
    from glitch_signal.agent.loop import llm as agent_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-admin-xyz")  # admin key cannot do inference
    with pytest.raises(RuntimeError, match="Admin key"):
        await agent_llm.complete("hi", client=_FakeHTTPX(_FakeResp(200, {"content": []})))


async def test_llm_complete_raises_on_error(monkeypatch):
    from glitch_signal.agent.loop import llm as agent_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    fake = _FakeHTTPX(_FakeResp(404, {"detail": "gone"}))
    with pytest.raises(RuntimeError):
        await agent_llm.complete("hi", client=fake)


class _SeqHTTPX:
    """Returns a queued sequence of responses; records how many posts happened."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = 0

    async def post(self, url, *, headers=None, json=None):
        self.posts += 1
        return self._responses.pop(0)


async def test_llm_complete_retries_transient_5xx(monkeypatch):
    from glitch_signal.agent.loop import llm as agent_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    fake = _SeqHTTPX([
        _FakeResp(503, {"error": "credential validation failed"}),
        _FakeResp(200, {"content": [{"type": "text", "text": "ok"}]}),
    ])
    out = await agent_llm.complete("hi", client=fake)
    assert out == "ok" and fake.posts == 2          # retried once, then succeeded


async def test_llm_complete_does_not_retry_4xx(monkeypatch):
    from glitch_signal.agent.loop import llm as agent_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    fake = _SeqHTTPX([_FakeResp(404, {"detail": "gone"})])
    with pytest.raises(RuntimeError):
        await agent_llm.complete("hi", client=fake)
    assert fake.posts == 1                           # client error → no retry


# ── run store (fake engine, no DB) — cross-worker status persistence ──
class _FakeConn:
    def __init__(self, sink, row=None):
        self._sink = sink
        self._row = row

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _FakeResult(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeEngine:
    def __init__(self, row=None):
        self.calls = []
        self._row = row

    def begin(self):
        return _FakeConn(self.calls, self._row)

    def connect(self):
        return _FakeConn(self.calls, self._row)


async def test_run_store_create_and_finish():
    from glitch_signal.agent.loop import runs
    eng = _FakeEngine()
    await runs.create_run("rid1", "glitch_executor", "do a thing", engine=eng)
    await runs.finish_run("rid1", {"steps": 3, "final": "done", "transcript": [{"a": 1}]}, engine=eng)
    sql = " ".join(c[0] for c in eng.calls)
    assert "INSERT INTO agent_runs" in sql and "UPDATE agent_runs" in sql
    # transcript is JSON-encoded for the jsonb bind
    assert eng.calls[1][1]["transcript"] == '[{"a": 1}]' and eng.calls[1][1]["status"] == "done"


async def test_run_store_get_decodes_transcript():
    from glitch_signal.agent.loop import runs
    row = {"run_id": "rid1", "brand_id": "b", "status": "done", "steps": 2,
           "final": "ok", "transcript": '[{"action":"recall"}]', "error": None}
    rec = await runs.get_run("rid1", engine=_FakeEngine(row=row))
    assert rec["status"] == "done" and rec["transcript"] == [{"action": "recall"}]


async def test_run_store_get_missing_returns_none():
    from glitch_signal.agent.loop import runs
    assert await runs.get_run("nope", engine=_FakeEngine(row=None)) is None


def test_system_prompt_carries_the_soul():
    # The agent's identity/mission/scope (SOUL.md) is prepended to every system prompt.
    from glitch_signal.agent.loop.prompt import system_prompt

    p = system_prompt()
    assert "Digital Marketing AGI" in p            # identity
    assert "Glitch Executor (GE)" in p and "30 days" in p   # current single-brand scope
    assert "Publishing is gated OFF" in p          # live guardrail
    assert "Operating rules" in p                  # operating rules block present
