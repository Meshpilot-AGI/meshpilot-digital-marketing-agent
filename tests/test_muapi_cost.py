"""MUapi cost calibration, checked against a real balance delta rather than a guess.

Reconciliation reported 46x "drift": 24 image generations as $0.0097 of true spend. That is four
hundredths of a cent per image, which is not a plausible price for nano-banana or Gemini image
generation — the number was the tell that a UNIT was wrong, not that our estimate was.

MUapi's balance is denominated in DOLLARS. It was being treated as credits at $0.01, dividing real
spend by 100. Once corrected, our estimate was revealed to be HALF the true cost — the dangerous
direction, since the daily cap was permitting about twice the spend it was configured for.
"""
from glitch_signal.analytics.cost import pricing, reconcile

# The observed window: balance 6.4324 -> 5.4625 across 24 generations.
BALANCE_DROP = 0.9699
CALLS = 24


def test_muapi_balance_is_treated_as_dollars_not_credits():
    assert pricing.muapi_credit_usd() == 1.0


def test_snapshot_records_the_real_unit_per_vendor():
    """Labelling every vendor's balance "credits" is what hid the error until real spend appeared."""
    assert reconcile.BALANCE_UNIT["muapi"] == "usd"
    assert reconcile.BALANCE_UNIT["heygen"] == "credits"


def test_estimate_now_matches_the_measured_spend():
    """The calibration test: estimate and reality must agree within a sane margin on real data."""
    actual = BALANCE_DROP * pricing.muapi_credit_usd()
    estimate = CALLS * pricing.muapi_cost("nano-banana-pro")
    drift = abs(estimate - actual) / actual
    assert drift < 0.15, f"estimate ${estimate:.4f} vs actual ${actual:.4f} — {drift:.0%} drift"


def test_the_old_settings_would_fail_this_calibration(monkeypatch):
    """Proves the test can fail: with the previous unit and rate, drift was ~46x."""
    monkeypatch.setenv("COST_MUAPI_CREDIT_USD", "0.01")
    monkeypatch.setenv("COST_MUAPI_DEFAULT_USD", "0.02")
    actual = BALANCE_DROP * pricing.muapi_credit_usd()
    estimate = CALLS * pricing.muapi_cost("x")
    assert abs(estimate - actual) / actual > 10


def test_per_call_estimate_is_not_below_the_measured_average():
    """Under-estimating is the unsafe direction: the daily cap would permit more real spend than
    configured, silently."""
    assert pricing.muapi_cost("x") >= (BALANCE_DROP / CALLS) * 0.9


def test_both_values_stay_env_overridable():
    """Vendor pricing changes without warning; correcting it must not need a deploy."""
    import os
    prev = os.environ.get("COST_MUAPI_DEFAULT_USD")
    os.environ["COST_MUAPI_DEFAULT_USD"] = "0.09"
    try:
        assert pricing.muapi_cost("x") == 0.09
    finally:
        os.environ.pop("COST_MUAPI_DEFAULT_USD", None)
        if prev is not None:
            os.environ["COST_MUAPI_DEFAULT_USD"] = prev
