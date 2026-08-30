"""DELIBERATION cloud fixes: configurable model (fallback to loop model) + run-record persistence."""
from __future__ import annotations

import json

from glitch_signal.agent.loop import conscience, llm as agent_llm, reckoning, runs


# ── Fix 1: model resolves from AGENT_DELIBERATION_MODEL, else the loop model ──
def test_deliberation_model_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_DELIBERATION_MODEL", "my-model")
    assert reckoning._model() == "my-model"
    assert conscience._model() == "my-model"


def test_deliberation_model_falls_back_to_loop_model(monkeypatch):
    monkeypatch.delenv("AGENT_DELIBERATION_MODEL", raising=False)
    expected = agent_llm._model(None)             # what the main loop uses
    assert reckoning._model() == expected
    assert conscience._model() == expected


# ── Fix 2: reckoning + conscience persist to the run record ──
class _FakeConn:
    def __init__(self, store, row=None):
        self._store, self._row = store, row

    async def execute(self, stmt, params=None):
        if params is not None:
            self._store["last"] = params
        row = self._row

        class _Res:
            def mappings(self_):
                class _M:
                    def first(self__):
                        return row
                return _M()
        return _Res()


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, store, row=None):
        self._store, self._row = store, row

    def begin(self):
        return _FakeCtx(_FakeConn(self._store))

    def connect(self):
        return _FakeCtx(_FakeConn(self._store, self._row))


async def test_finish_run_persists_deliberation():
    store: dict = {}
    res = {"steps": 3, "final": "done", "transcript": [{"action": "publish"}],
           "reckoning": {"met": "yes", "trust": "self-assessed"},
           "conscience": {"verdict": "pass", "notes": "compliant"}}
    await runs.finish_run("r1", res, engine=_FakeEngine(store))
    delib = json.loads(store["last"]["deliberation"])
    assert delib["reckoning"]["met"] == "yes" and delib["conscience"]["verdict"] == "pass"


async def test_finish_run_empty_deliberation_when_absent():
    store: dict = {}
    await runs.finish_run("r1", {"steps": 1, "final": "x", "transcript": []}, engine=_FakeEngine(store))
    assert store["last"]["deliberation"] == "{}"


async def test_get_run_exposes_deliberation_top_level():
    row = {"run_id": "r1", "brand_id": "b", "status": "done", "steps": 3, "final": "f",
           "transcript": "[]", "error": None,
           "deliberation": '{"reckoning":{"met":"no"},"conscience":{"verdict":"concerns"}}'}
    rec = await runs.get_run("r1", engine=_FakeEngine({}, row=row))
    assert rec["reckoning"]["met"] == "no" and rec["conscience"]["verdict"] == "concerns"
    assert "deliberation" not in rec           # unpacked to the top level
