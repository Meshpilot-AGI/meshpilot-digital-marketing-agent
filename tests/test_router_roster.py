"""The roster's own invariants (ROUTER). These do not call the network — `scripts/probe_router_models.py`
does that, because reachability is evidence and cannot be asserted from a file."""
from __future__ import annotations

from glitch_signal.agent.loop import routing


def test_every_tier_actually_has_a_fallback():
    """The module documents native failover. A tier whose second and third entries cannot be called
    has none — which was true of `critical` and `moderate` and invisible from here."""
    for tier, models in routing.TIERS.items():
        assert len(models) >= 2, tier
        assert len(set(models)) == len(models), f"{tier} lists the same model twice"


def test_no_tier_still_lists_a_model_this_account_cannot_reach():
    """Pins the removal so a future session cannot reintroduce them from memory."""
    for tier, models in routing.TIERS.items():
        bad = set(models) & set(routing.UNREACHABLE_2026_09_02)
        assert not bad, f"{tier} lists unreachable {sorted(bad)}"


def test_a_tier_does_not_fall_back_onto_its_own_primary():
    """`complex` falling back to `sonnet-5` when `sonnet-5` is what just failed buys nothing."""
    for tier, models in routing.TIERS.items():
        assert models[1] != models[0], tier
