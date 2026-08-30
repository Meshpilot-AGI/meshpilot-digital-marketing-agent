"""DELIBERATION wiring — reckoning + conscience attach to the run result + episode, flag-gated OFF."""
from __future__ import annotations

from glitch_signal.agent.loop import conscience, reckoning
from glitch_signal.agent.loop.runner import run


def _settings_proxy(monkeypatch, **flags):
    """Override only the deliberation flags; proxy everything else to real settings."""
    from glitch_signal.config import settings as _s
    real = _s()

    class _Over:
        def __getattr__(self, k):
            return flags[k] if k in flags else getattr(real, k)

    monkeypatch.setattr("glitch_signal.config.settings", lambda: _Over())


def _done_llm():
    async def _llm(messages, *, tools=None, system=None):
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "made a draft"}]}
    return _llm


def _rec_exec(store):
    async def _e(tool, args, brand_id):
        if tool == "remember":
            store.append(args.get("content", ""))
        return "[]"
    return _e


async def test_deliberation_off_by_default(monkeypatch):
    called = {"n": 0}

    async def _spy_exp(*a, **k):
        called["n"] += 1
        return "x"

    monkeypatch.setattr(reckoning, "expectation", _spy_exp)
    store: list = []
    res = await run("b", "g", llm=_done_llm(), execute=_rec_exec(store), scope="full")
    assert "reckoning" not in res and "conscience" not in res
    assert called["n"] == 0                                 # flag off → not even the expectation runs
    assert "Reckoning" not in store[-1] and "Conscience" not in store[-1]


async def test_deliberation_on_attaches_to_result_and_episode(monkeypatch):
    _settings_proxy(monkeypatch, agent_reckoning_enabled=True, agent_conscience_enabled=True)

    async def _exp(goal, seed, **k):
        return "expected a draft"

    async def _reck(goal, exp, transcript, final, **k):
        return {"met": "yes", "attribution": "none", "discrepancy": "", "lesson": "",
                "trust": "self-assessed", "expected": exp}

    async def _rev(goal, output, **k):
        return {"verdict": "pass", "notes": "compliant"}

    monkeypatch.setattr(reckoning, "expectation", _exp)
    monkeypatch.setattr(reckoning, "reckon", _reck)
    monkeypatch.setattr(conscience, "review", _rev)

    store: list = []
    res = await run("b", "g", llm=_done_llm(), execute=_rec_exec(store), scope="full")
    assert res["reckoning"]["met"] == "yes" and res["conscience"]["verdict"] == "pass"
    assert "Reckoning[self-assessed]: met=yes" in store[-1] and "Conscience: pass" in store[-1]
