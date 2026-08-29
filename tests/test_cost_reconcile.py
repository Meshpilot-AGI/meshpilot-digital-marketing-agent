"""COST-METER INC-2 — MUapi/HeyGen capture pricing + balance-delta reconciliation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from glitch_signal.analytics.cost import pricing, reconcile

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


# ── pricing (credit vendors) ──
def test_muapi_cost_default_and_override(monkeypatch):
    monkeypatch.delenv("COST_MUAPI_MODEL_USD", raising=False)
    monkeypatch.setenv("COST_MUAPI_DEFAULT_USD", "0.05")
    assert pricing.muapi_cost("whatever") == 0.05
    monkeypatch.setenv("COST_MUAPI_MODEL_USD", '{"pricey-model": 0.5}')
    assert pricing.muapi_cost("pricey-model") == 0.5
    assert pricing.muapi_cost("other") == 0.05  # falls back to default


def test_heygen_cost_credits_to_usd(monkeypatch):
    monkeypatch.setenv("COST_HEYGEN_CREDIT_USD", "0.30")
    monkeypatch.setenv("COST_HEYGEN_DEFAULT_CREDITS", "2")
    credits, usd = pricing.heygen_cost("avatar-video")
    assert credits == 2.0 and usd == pytest.approx(0.60)


# ── engine capture ──
async def test_muapi_engine_meter_records_with_brand(monkeypatch):
    from glitch_signal.media.generation.engines import muapi as muapi_engine

    seen = {}

    async def _rec(**kw):
        seen.update(kw)
    monkeypatch.setattr("glitch_signal.analytics.cost.record_usage", _rec)
    monkeypatch.setattr("glitch_signal.analytics.cost.get_brand", lambda: "glitch_executor")
    await muapi_engine._meter("flux-model", "req-123")
    assert seen["vendor"] == "muapi" and seen["brand_id"] == "glitch_executor"
    assert seen["model"] == "flux-model" and seen["cost_usd"] > 0


async def test_heygen_engine_meter_records_credits(monkeypatch):
    from glitch_signal.media.generation.engines import heygen as heygen_engine

    seen = {}

    async def _rec(**kw):
        seen.update(kw)
    monkeypatch.setattr("glitch_signal.analytics.cost.record_usage", _rec)
    monkeypatch.setattr("glitch_signal.analytics.cost.get_brand", lambda: "glitch_executor")
    await heygen_engine._meter("talking-avatar", "vid-9")
    assert seen["vendor"] == "heygen" and seen["operation"] == "video.generate"
    assert seen["units"]["credits"] >= 1


# ── reconcile fake engine (routes by SQL) ──
class _Result:
    def __init__(self, first):
        self._first = first

    def mappings(self):
        return self

    def first(self):
        return self._first


class _Conn:
    def __init__(self, sink, prev, summ):
        self._sink, self._prev, self._summ = sink, prev, summ

    async def execute(self, stmt, params=None):
        s = str(stmt).lower()
        self._sink.append((s, params))
        if "from balance_snapshots" in s:
            return _Result(self._prev)
        if "sum(cost_usd)" in s:
            return _Result(self._summ)
        if "insert into balance_snapshots" in s:
            return _Result({"id": "snap-1", "created_at": NOW})
        return _Result(None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Engine:
    def __init__(self, prev=None, summ=None):
        self.calls = []
        self._prev, self._summ = prev, summ

    def begin(self):
        return _Conn(self.calls, self._prev, self._summ)

    def connect(self):
        return _Conn(self.calls, self._prev, self._summ)


def _fake_fetcher(balance, raw=None):
    async def _f(client):
        return balance, (raw or {})
    return _f


async def test_reconcile_baseline_when_no_prev(monkeypatch):
    monkeypatch.setitem(reconcile._FETCHERS, "heygen", _fake_fetcher(50.0))
    eng = _Engine(prev=None)
    out = await reconcile.run(["heygen"], now=NOW, engine=eng)
    v = out["vendors"][0]
    assert v["status"] == "baseline" and v["balance"] == 50.0


async def test_reconcile_computes_drift(monkeypatch):
    monkeypatch.setitem(reconcile._FETCHERS, "heygen", _fake_fetcher(90.0))
    monkeypatch.setenv("COST_HEYGEN_CREDIT_USD", "0.30")
    prev = {"balance": 100.0, "created_at": NOW - timedelta(hours=1)}
    summ = {"usd": 2.40, "n": 4}  # our estimate; vendor_actual = 10 credits * 0.30 = 3.00
    eng = _Engine(prev=prev, summ=summ)
    out = await reconcile.run(["heygen"], now=NOW, engine=eng)
    v = out["vendors"][0]
    assert v["status"] == "reconciled"
    assert v["delta_credits"] == 10.0
    assert v["vendor_actual_usd"] == pytest.approx(3.0)
    assert v["our_estimate_usd"] == pytest.approx(2.40)
    assert v["drift"] == pytest.approx((2.40 - 3.0) / 3.0, abs=1e-3)  # -0.20 → alerts


async def test_reconcile_unavailable_is_graceful(monkeypatch):
    monkeypatch.setitem(reconcile._FETCHERS, "muapi", _fake_fetcher(None, {"error": "boom"}))
    eng = _Engine(prev=None)
    out = await reconcile.run(["muapi"], now=NOW, engine=eng)
    v = out["vendors"][0]
    assert v["status"] == "unavailable" and v["balance"] is None
    # a snapshot was still written (for audit)
    assert any("insert into balance_snapshots" in s for s, _ in eng.calls)


async def test_reconcile_capability_dispatches(monkeypatch):
    from glitch_signal.agent.cron import capabilities

    async def _run(vendors=None):
        return {"reconciled_at": "x", "vendors": [], "got": vendors}
    monkeypatch.setattr(reconcile, "run", _run)
    out = await capabilities.get("reconcile")("glitch_executor", {"vendors": ["heygen"]})
    assert out["got"] == ["heygen"]
