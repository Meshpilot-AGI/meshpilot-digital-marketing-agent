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
