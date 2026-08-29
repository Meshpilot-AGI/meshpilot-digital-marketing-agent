"""AGENT-LOOP — ReAct loop mechanics with a scripted LLM + fake tools (no network)."""
from __future__ import annotations

import pytest

from glitch_signal.agent.loop import parse_action, run


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, prompt, *, system=None):
        self.calls.append(prompt)
        return self.responses.pop(0) if self.responses else '{"final":"(out of script)"}'


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


# ── parse_action ──────────────────────────────────────────────────────
def test_parse_action_clean():
    assert parse_action('{"final":"x"}') == {"final": "x"}


def test_parse_action_wrapped_in_prose():
    raw = 'Sure!\n```json\n{"action":"recall","args":{"query":"who"}}\n```'
    assert parse_action(raw) == {"action": "recall", "args": {"query": "who"}}


def test_parse_action_none():
    assert parse_action("no json here") is None


# ── loop ──────────────────────────────────────────────────────────────
async def test_loop_runs_actions_and_writes_episode():
    llm = ScriptedLLM([
        '{"thought":"make it","action":"generate_media","args":{"recipe":"muapi-logo-creator","inputs":{}}}',
        '{"thought":"done","final":"made a logo"}',
    ])
    ex = FakeExec()
    res = await run("glitch_executor", "make a logo", llm=llm, execute=ex)
    assert res["final"] == "made a logo" and res["steps"] == 2
    called = [c[0] for c in ex.calls]
    assert called[0] == "recall"          # seed recall before the loop
    assert "generate_media" in called
    assert called[-1] == "remember"       # episode write at the end


async def test_loop_denies_publish():
    llm = ScriptedLLM([
        '{"action":"publish","args":{"platform":"x","text":"hi"}}',
        '{"final":"stopped — publishing is off"}',
    ])
    ex = FakeExec()
    res = await run("glitch_executor", "post to X", llm=llm, execute=ex)
    assert res["transcript"][0]["observation"].startswith("DENIED")
    assert not any(c[0] == "publish" for c in ex.calls)  # never executed


async def test_loop_enforces_media_budget(monkeypatch):
    # 3 media-gen attempts, then finish; policy caps at 2 → 3rd is DENIED, never executed.
    from glitch_signal.agent.loop import policy
    monkeypatch.setattr(policy, "from_config", lambda: policy.Policy(max_media_per_run=2))
    llm = ScriptedLLM([
        '{"action":"generate_media","args":{"recipe":"muapi-logo-creator","inputs":{}}}',
        '{"action":"generate_media","args":{"recipe":"muapi-logo-creator","inputs":{}}}',
        '{"action":"generate_media","args":{"recipe":"muapi-logo-creator","inputs":{}}}',
        '{"final":"done"}',
    ])
    ex = FakeExec()
    res = await run("b", "make logos", llm=llm, execute=ex, max_steps=6)
    gen_calls = [c for c in ex.calls if c[0] == "generate_media"]
    assert len(gen_calls) == 2                                  # only 2 actually executed
    assert res["transcript"][2]["observation"].startswith("DENIED")  # 3rd blocked by budget


async def test_loop_tolerates_unparseable():
    llm = ScriptedLLM(["not json at all", '{"final":"ok"}'])
    ex = FakeExec()
    res = await run("b", "g", llm=llm, execute=ex)
    assert res["final"] == "ok"
    assert any("error" in t for t in res["transcript"])


async def test_loop_stops_at_max_steps():
    llm = ScriptedLLM(['{"action":"recall","args":{}}'] * 10)  # never finishes
    ex = FakeExec()
    res = await run("b", "g", llm=llm, execute=ex, max_steps=3)
    assert res["final"] is None and res["steps"] == 3
    assert ex.calls[-1][0] == "remember"  # episode still written on timeout


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
    assert fake.posted["json"]["system"] == "sys"            # system is top-level, not a message
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
