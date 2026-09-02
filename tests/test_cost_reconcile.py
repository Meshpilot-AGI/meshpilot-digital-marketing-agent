"""COST-METER INC-2 — MUapi/HeyGen capture pricing + balance-delta reconciliation."""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from glitch_signal.analytics.cost import pricing, reconcile

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "supabase" / "migrations"


# ── historical MUapi rows must be relabelled, not just future ones (finding: "Historical units
#    remain incorrect") ─────────────────────────────────────────────────────────────────────────
def test_a_migration_relabels_historical_muapi_snapshots_as_usd():
    """MUapi's balance was always dollar-denominated, but rows written before the fix are stuck
    with balance_unit='credits'. A runtime-only fix leaves the audit trail permanently mixed."""
    candidates = [p for p in _MIGRATIONS.glob("*.sql") if "balance_snapshot" in p.name]
    hit = [p for p in candidates
          if "muapi" in p.read_text().lower() and "usd" in p.read_text().lower()
          and "update" in p.read_text().lower()]
    assert hit, "no migration found that relabels historical muapi balance_snapshots to usd"


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
    """The credit->USD conversion path, on a vendor whose balance really is credits.

    (This used HeyGen until its balance moved to the wallet's USD figure — see the heygen test
    below and `docs/vendors/heygen.md`.)"""
    monkeypatch.setitem(reconcile._FETCHERS, "higgsfield", _fake_fetcher(90.0))
    monkeypatch.setenv("COST_HIGGSFIELD_CREDIT_USD", "0.30")
    prev = {"balance": 100.0, "created_at": NOW - timedelta(hours=1)}
    summ = {"usd": 2.40, "n": 4}  # our estimate; vendor_actual = 10 credits * 0.30 = 3.00
    eng = _Engine(prev=prev, summ=summ)
    out = await reconcile.run(["higgsfield"], now=NOW, engine=eng)
    v = out["vendors"][0]
    assert v["status"] == "reconciled"
    assert v["delta_credits"] == 10.0
    assert v["vendor_actual_usd"] == pytest.approx(3.0)
    assert v["our_estimate_usd"] == pytest.approx(2.40)
    assert v["drift"] == pytest.approx((2.40 - 3.0) / 3.0, abs=1e-3)  # -0.20 → alerts


async def test_reconcile_muapi_reports_a_usd_delta_not_credits(monkeypatch):
    """MUapi's balance is dollar-denominated: labelling its delta `delta_credits` exposes a false
    unit to every consumer of this result. It must be reported as `delta_usd` with `balance_unit`
    stated explicitly, while credit vendors keep `delta_credits` for compatibility."""
    monkeypatch.setitem(reconcile._FETCHERS, "muapi", _fake_fetcher(5.4625))
    monkeypatch.setenv("COST_MUAPI_CREDIT_USD", "1.0")
    prev = {"balance": 6.4324, "created_at": NOW - timedelta(hours=1)}
    summ = {"usd": 1.0, "n": 24}
    eng = _Engine(prev=prev, summ=summ)
    out = await reconcile.run(["muapi"], now=NOW, engine=eng)
    v = out["vendors"][0]
    assert v["status"] == "reconciled"
    assert v["balance_unit"] == "usd"
    assert "delta_usd" in v
    assert "delta_credits" not in v
    assert v["delta_usd"] == pytest.approx(0.9699, abs=1e-4)


async def test_reconcile_heygen_reports_a_credit_delta(monkeypatch):
    """HeyGen renders bill PLAN CREDITS, so its balance is credits and converts via the credit rate.

    Briefly reconciled against the USD wallet instead — wrong number entirely: the wallet held
    $1.05 while `details.plan_credit` (the pool renders actually draw down) held 1,091."""
    monkeypatch.setitem(reconcile._FETCHERS, "heygen", _fake_fetcher(90.0))
    monkeypatch.setenv("COST_HEYGEN_CREDIT_USD", "0.30")
    prev = {"balance": 100.0, "created_at": NOW - timedelta(hours=1)}
    summ = {"usd": 2.40, "n": 4}
    eng = _Engine(prev=prev, summ=summ)
    out = await reconcile.run(["heygen"], now=NOW, engine=eng)
    v = out["vendors"][0]
    assert v["balance_unit"] == "credits"
    assert v["delta_credits"] == 10.0
    assert "delta_usd" not in v
