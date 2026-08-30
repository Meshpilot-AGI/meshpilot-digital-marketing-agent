"""DELIBERATION Phase 1 — reckoning: expectation (pre-act) + self-assessment (post-act)."""
from __future__ import annotations

from glitch_signal.agent.loop import reckoning


def _fake(reply: str):
    async def _c(prompt, *, system=None, model=None, timeout_s=90, **kw):
        return reply
    return _c


async def test_expectation_returns_text():
    exp = await reckoning.expectation("post a logo", "recall…",
                                      complete=_fake("I expect a logo draft; success = on-brand."))
    assert "logo" in exp.lower()


async def test_expectation_failsoft_on_error():
    async def _boom(*a, **k):
        raise RuntimeError("api down")
    assert await reckoning.expectation("g", "s", complete=_boom) == ""   # never raises into the run


async def test_reckon_parses_structured_verdict():
    reply = ('{"met":"no","discrepancy":"no draft produced","attribution":"tool-failure",'
             '"lesson":"check the media tool first"}')
    r = await reckoning.reckon("make a logo", "expected a logo",
                               [{"action": "generate_media", "observation": "ERROR"}], "(none)",
                               complete=_fake(reply))
    assert r["met"] == "no" and r["attribution"] == "tool-failure"
    assert r["trust"] == "self-assessed"                    # never a verified signal
    assert "check the media tool" in r["lesson"]


async def test_reckon_tolerates_prose_around_json():
    reply = 'Here is my reckoning:\n{"met":"yes","attribution":"none","lesson":""}\nDone.'
    r = await reckoning.reckon("g", "e", [], "f", complete=_fake(reply))
    assert r["met"] == "yes" and r["trust"] == "self-assessed"


async def test_reckon_empty_on_garbage():
    assert await reckoning.reckon("g", "e", [], "f", complete=_fake("no json here")) == {}


async def test_reckon_normalizes_unknown_met():
    r = await reckoning.reckon("g", "e", [], "f", complete=_fake('{"met":"totally","attribution":"my-plan"}'))
    assert r["met"] == "unknown"


async def test_reckon_failsoft_on_error():
    async def _boom(*a, **k):
        raise RuntimeError("boom")
    assert await reckoning.reckon("g", "e", [], "f", complete=_boom) == {}
