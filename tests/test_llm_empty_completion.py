"""An empty completion is a failure, not an answer (ROUTER).

The defect this pins: a reasoning model given a budget sized for the ANSWER spends it all on
thinking and returns `content: null` / `finish_reason: "length"`. That was translated into `""` and
handed back as a successful result, so every caller on the affected tier silently received an empty
string and carried on — which is how an entire model tier stayed broken unnoticed.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.loop import llm


def _body(text=None, finish="stop", out=10, model="z-ai/glm-5.2"):
    return {"model": model, "id": "gen-1",
            "choices": [{"finish_reason": finish, "message": {"content": text}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": out}}


class _Send:
    """Stands in for the HTTP round-trip, recording the budget each attempt asked for."""

    def __init__(self, *bodies):
        self.bodies, self.budgets = list(bodies), []

    async def __call__(self, payload, *, timeout_s, client):
        self.budgets.append(payload["max_tokens"])
        return self.bodies[min(len(self.budgets) - 1, len(self.bodies) - 1)]


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(llm, "_meter", _noop)


async def _chat(monkeypatch, sender, **kw):
    monkeypatch.setattr(llm, "_send", sender)
    return await llm._chat([{"role": "user", "content": "hi"}], system=None, tools=None,
                           max_tokens=kw.pop("max_tokens", 200), timeout_s=30, client=None, **kw)


async def test_a_normal_answer_is_returned_untouched(monkeypatch):
    send = _Send(_body("ok"))
    resp = await _chat(monkeypatch, send)
    assert resp["content"][0]["text"] == "ok"
    assert send.budgets == [200]                     # no retry, no escalation


async def test_the_thinking_budget_case_is_retried_once_at_a_larger_budget(monkeypatch):
    """Budget exhaustion is mechanically identifiable AND mechanically fixable, so it earns exactly
    one retry — measured: 50 tokens returns nothing, 400 returns the answer."""
    send = _Send(_body(None, finish="length", out=200), _body("ok"))
    resp = await _chat(monkeypatch, send, max_tokens=200)
    assert resp["content"][0]["text"] == "ok"
    assert send.budgets == [200, 1500]               # floor, not merely 4x a tiny budget


async def test_the_retry_is_capped(monkeypatch):
    send = _Send(_body(None, finish="length", out=4000), _body("ok"))
    await _chat(monkeypatch, send, max_tokens=4000)
    assert send.budgets[1] == 8000                   # not 16000


async def test_an_already_generous_budget_is_not_retried(monkeypatch):
    """At the ceiling the budget is not the explanation any more, so retrying just spends money."""
    send = _Send(_body(None, finish="length", out=8000))
    with pytest.raises(RuntimeError, match="empty completion"):
        await _chat(monkeypatch, send, max_tokens=8000)
    assert len(send.budgets) == 1


async def test_a_still_empty_retry_raises_rather_than_returning_nothing(monkeypatch):
    send = _Send(_body(None, finish="length"), _body(None, finish="length"))
    with pytest.raises(RuntimeError, match="empty completion"):
        await _chat(monkeypatch, send)


async def test_an_unexplained_empty_answer_raises_immediately(monkeypatch):
    """`finish_reason: stop` with no content is not a budget problem — it is unexplained, and an
    unexplained empty answer is a failure, not a result."""
    send = _Send(_body(None, finish="stop"))
    with pytest.raises(RuntimeError, match="empty completion"):
        await _chat(monkeypatch, send)
    assert len(send.budgets) == 1


async def test_the_error_names_what_would_be_needed_to_diagnose_it(monkeypatch):
    send = _Send(_body(None, finish="stop", out=7, model="z-ai/glm-5.2"))
    with pytest.raises(RuntimeError) as exc:
        await _chat(monkeypatch, send)
    msg = str(exc.value)
    assert "z-ai/glm-5.2" in msg and "end_turn" in msg and "max_tokens=200" in msg


async def test_a_tool_call_with_no_prose_is_a_real_answer(monkeypatch):
    """The check is "nothing came back", not "no text came back" — a tool call IS the response."""
    body = _body(None)
    body["choices"][0]["message"]["tool_calls"] = [
        {"id": "t1", "function": {"name": "search", "arguments": "{}"}}]
    body["choices"][0]["finish_reason"] = "tool_calls"
    resp = await _chat(monkeypatch, _Send(body))
    assert resp["content"][0]["type"] == "tool_use"
