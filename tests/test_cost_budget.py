"""COST-METER INC-3 — per-brand daily budget gate + max_steps ceiling."""
from __future__ import annotations

import pytest

from glitch_signal.analytics.cost import budget


# ── steps ceiling (fixes unbounded max_steps, #94) ──
def test_clamp_steps_caps_to_ceiling(monkeypatch):
    monkeypatch.setattr(budget, "steps_ceiling", lambda: 12)
    assert budget.clamp_steps(9999) == 12
    assert budget.clamp_steps(5) == 5
    assert budget.clamp_steps(0) == 1        # floor at 1
    assert budget.clamp_steps(-3) == 1
    assert budget.clamp_steps("bad") == 1    # non-int → 1


# ── per-brand cap resolution ──
def test_brand_daily_cap_env_override(monkeypatch):
    monkeypatch.setenv("GE_DAILY_BUDGET_USD", "25")
    assert budget.brand_daily_cap("glitch_executor") == 25.0


def test_brand_daily_cap_default_unlimited(monkeypatch):
    monkeypatch.delenv("GE_DAILY_BUDGET_USD", raising=False)
    # global default is 0.0 (unlimited) unless configured
    assert budget.brand_daily_cap("glitch_executor") == 0.0


# ── status + check ──
def _fake_spend(usd):
    async def _f(brand, from_ts, to_ts, *, engine=None):
        return {"total_usd": usd, "by_vendor": []}
    return _f


async def test_budget_status_under_cap(monkeypatch):
    monkeypatch.setattr(budget, "brand_daily_cap", lambda b: 10.0)
    monkeypatch.setattr("glitch_signal.analytics.cost.meter.spend_summary", _fake_spend(3.0))
    s = await budget.budget_status("glitch_executor")
    assert s["over"] is False and s["remaining_usd"] == pytest.approx(7.0) and s["pct"] == pytest.approx(0.3)


async def test_budget_status_over_cap(monkeypatch):
    monkeypatch.setattr(budget, "brand_daily_cap", lambda b: 10.0)
    monkeypatch.setattr("glitch_signal.analytics.cost.meter.spend_summary", _fake_spend(12.5))
    s = await budget.budget_status("glitch_executor")
    assert s["over"] is True


async def test_budget_unlimited_never_over(monkeypatch):
    monkeypatch.setattr(budget, "brand_daily_cap", lambda b: 0.0)
    monkeypatch.setattr("glitch_signal.analytics.cost.meter.spend_summary", _fake_spend(9999.0))
    s = await budget.budget_status("glitch_executor")
    assert s["over"] is False and s["unlimited"] is True


async def test_budget_fails_open_on_read_error(monkeypatch):
    monkeypatch.setattr(budget, "brand_daily_cap", lambda b: 10.0)

    async def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr("glitch_signal.analytics.cost.meter.spend_summary", _boom)
    s = await budget.budget_status("glitch_executor")
    assert s["over"] is False  # fail-open: a broken meter never blocks work


async def test_check_denies_when_over(monkeypatch):
    monkeypatch.setattr(budget, "brand_daily_cap", lambda b: 5.0)
    monkeypatch.setattr("glitch_signal.analytics.cost.meter.spend_summary", _fake_spend(6.0))
    allowed, reason = await budget.check("glitch_executor")
    assert allowed is False and "over daily budget" in reason


async def test_check_allows_when_under(monkeypatch):
    monkeypatch.setattr(budget, "brand_daily_cap", lambda b: 5.0)
    monkeypatch.setattr("glitch_signal.analytics.cost.meter.spend_summary", _fake_spend(1.0))
    allowed, reason = await budget.check("glitch_executor")
    assert allowed is True and reason == ""


# ── runner clamps steps (integration, injected fakes, no DB) ──
async def test_runner_clamps_max_steps(monkeypatch):
    from glitch_signal.agent.loop import runner

    monkeypatch.setattr(budget, "steps_ceiling", lambda: 3)
    seen_steps = []

    async def _llm(messages, *, tools=None, system=None):
        seen_steps.append(1)
        # always a tool_use → never finishes, runs until max_steps
        return {"stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": "t", "name": "recall", "input": {}}]}

    async def _exec(tool, args, brand_id):
        return "ok"

    res = await runner.run("glitch_executor", "do a thing", llm=_llm, execute=_exec, max_steps=9999)
    # clamped to 3 → at most 3 LLM calls, not 9999
    assert len(seen_steps) <= 3 and res["steps"] <= 3
