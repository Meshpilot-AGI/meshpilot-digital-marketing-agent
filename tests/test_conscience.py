"""DELIBERATION Phase 2 — conscience: an independent critic vs agent/CONSCIENCE.md."""
from __future__ import annotations

from glitch_signal.agent.loop import conscience


def _fake(reply: str):
    async def _c(prompt, *, system=None, model=None, timeout_s=90, **kw):
        _c.system, _c.prompt = system, prompt
        return reply
    return _c


def test_constitution_loads():
    con = conscience.constitution()
    assert "Truthful claims" in con and "escalate" in con.lower()


async def test_review_flags_concerns_and_is_independent():
    c = _fake('{"verdict":"concerns","notes":"Principle 2 — fabricated social proof."}')
    out = await conscience.review("write a testimonial",
                                  "500 five-star reviews say we are the best!", complete=c)
    assert out["verdict"] == "concerns" and "Principle 2" in out["notes"]
    # independence: constitution in the system prompt; the output-under-review in the user prompt.
    # review()'s signature is (goal, output) — it structurally cannot see the actor's transcript.
    assert "CONSTITUTION" in c.system
    assert "five-star reviews" in c.prompt and "five-star reviews" not in c.system


async def test_review_pass():
    out = await conscience.review("g", "An honest product description.",
                                  complete=_fake('{"verdict":"pass","notes":"compliant"}'))
    assert out["verdict"] == "pass"


async def test_review_unknown_verdict_fails_cautious():
    out = await conscience.review("g", "some output",
                                  complete=_fake('{"verdict":"looksfine","notes":"x"}'))
    assert out["verdict"] == "concerns"                     # unparseable verdict → cautious, not pass


async def test_review_empty_output_skips():
    assert await conscience.review("g", "   ", complete=_fake('{"verdict":"pass"}')) == {}


async def test_review_failsoft_on_error():
    async def _boom(*a, **k):
        raise RuntimeError("boom")
    assert await conscience.review("g", "output", complete=_boom) == {}
