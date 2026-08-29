"""COST-METER INC-1 — per-brand spend metering (context + price book + meter + rollup)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from glitch_signal.analytics.cost import brand_scope, get_brand, record_usage, set_brand, spend_summary
from glitch_signal.analytics.cost.pricing import anthropic_cost, higgsfield_cost

# asyncio_mode = "auto" (pyproject) runs the async tests; sync tests stay unmarked.


# ── brand context ──
def test_brand_context_set_get_and_scope():
    set_brand(None)
    assert get_brand() is None
    set_brand("glitch_executor")
    assert get_brand() == "glitch_executor"
    with brand_scope("other_brand"):
        assert get_brand() == "other_brand"
    assert get_brand() == "glitch_executor"  # restored on scope exit


# ── price book ──
def test_anthropic_cost_tokens_to_usd():
    # 1M input + 1M output on haiku ($1 / $5 per MTok) = $6.00
    usd = anthropic_cost("claude-haiku-4-5-20251001",
                         {"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert usd == pytest.approx(6.0)


def test_anthropic_cost_counts_cache_tokens():
    usd = anthropic_cost("claude-haiku-4-5-20251001",
                         {"input_tokens": 0, "output_tokens": 0,
                          "cache_read_input_tokens": 1_000_000})  # $0.10 / MTok
    assert usd == pytest.approx(0.10)


def test_anthropic_cost_unknown_model_falls_back():
    # unknown model must not raise — it falls back to the first price entry
    assert anthropic_cost("mystery-model", {"input_tokens": 1_000_000}) > 0


def test_higgsfield_cost_credits_to_usd(monkeypatch):
    monkeypatch.setenv("COST_HIGGSFIELD_CREDIT_USD", "0.01")
    credits, usd = higgsfield_cost("higgsfield-ai/dop/standard")  # 9 credits
    assert credits == 9.0
    assert usd == pytest.approx(0.09)


def test_higgsfield_cost_zero_for_soul():
    credits, usd = higgsfield_cost("higgsfield-ai/soul/v2/standard")
    assert credits == 0.0 and usd == 0.0


# ── fake engine (no DB) ──
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, sink, rows):
        self._sink, self._rows = sink, rows

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _FakeResult(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    def begin(self):
        return _FakeConn(self.calls, self._rows)

    def connect(self):
        return _FakeConn(self.calls, self._rows)


# ── meter ──
async def test_record_usage_inserts_row():
    eng = _FakeEngine()
    await record_usage(brand_id="glitch_executor", vendor="anthropic", operation="chat",
                       model="claude-haiku-4-5-20251001",
                       units={"input_tokens": 10}, cost_usd=0.001, request_id="req_1", engine=eng)
    assert len(eng.calls) == 1
    stmt, params = eng.calls[0]
    assert "insert into usage_events" in stmt.lower()
    assert params["brand_id"] == "glitch_executor"
    assert params["vendor"] == "anthropic"
    assert params["cost_usd"] == 0.001


async def test_record_usage_defaults_unattributed_brand():
    eng = _FakeEngine()
    await record_usage(brand_id=None, vendor="higgsfield", operation="image.generate", engine=eng)
    assert eng.calls[0][1]["brand_id"] == "unattributed"


async def test_record_usage_is_fail_soft():
    class _Boom:
        def begin(self):
            raise RuntimeError("db down")

    # must not raise — metering never breaks the generation it measures
    await record_usage(brand_id="b", vendor="anthropic", operation="chat", engine=_Boom())


async def test_spend_summary_rolls_up_by_vendor():
    rows = [
        {"vendor": "anthropic", "events": 3, "cost_usd": 0.25},
        {"vendor": "higgsfield", "events": 2, "cost_usd": 0.18},
    ]
    eng = _FakeEngine(rows=rows)
    to_ts = datetime.now(timezone.utc)
    from_ts = to_ts - timedelta(days=30)
    out = await spend_summary("glitch_executor", from_ts, to_ts, engine=eng)
    assert out["brand_id"] == "glitch_executor"
    assert out["total_events"] == 5
    assert out["total_usd"] == pytest.approx(0.43)
    assert {v["vendor"] for v in out["by_vendor"]} == {"anthropic", "higgsfield"}
