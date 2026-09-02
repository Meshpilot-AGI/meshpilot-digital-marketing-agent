"""The router must actually be in play — every agent LLM call routes through a tier.

Two ways a call silently bypassed it:

  * Omitting `tier=` entirely, so the call fell to the default model rather than a routed list.
  * Passing `model=`, which `_resolve_models` treats as an override and returns as a single-element
    list — so the call also forfeits the cross-provider failover the router exists to give. That is
    how the conscience critic ended up pinned to Haiku with no fallback: if that one model was
    rate-limited the review returned {} and every post was held.
"""
import pathlib
import re

from glitch_signal.agent.loop import conscience, reckoning, routing

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "glitch_signal"

# The agent's own reasoning path. Legacy sub-packages (influencer/, nodes/, media/) predate the
# router and are out of scope for this guard.
ROUTED = ["agent/social/ideate.py", "agent/social/plan.py", "agent/social/captions.py",
          "agent/learn/outcomes.py", "agent/loop/conscience.py", "agent/loop/reckoning.py"]


def test_every_agent_llm_call_declares_a_tier():
    missing = []
    for rel in ROUTED:
        text = (SRC / rel).read_text()
        for m in re.finditer(r"await complete(?:_messages)?\((.{0,400}?)\)\n", text, re.DOTALL):
            if "tier=" not in m.group(1):
                missing.append(f"{rel}: {m.group(1)[:70].strip()}")
    assert not missing, "LLM call without a tier — bypasses the router:\n  " + "\n  ".join(missing)


def test_the_safety_gate_runs_on_the_strongest_tier():
    """The critic is the last thing between the agent and the public. It ran on the CHEAPEST model
    (Haiku, pinned, no fallback) until this was fixed."""
    assert conscience.CRITIC_TIER == "critical"
    assert routing.resolve("critical")[0] == "anthropic/claude-opus-5"


def test_deliberation_routes_rather_than_pinning():
    assert reckoning.DELIBERATION_TIER in routing.TIERS


def test_an_unset_override_means_route_not_pin():
    """`AGENT_DELIBERATION_MODEL` stays an escape hatch, but unset must mean "use the tier"."""
    assert conscience._model() is None


def test_every_tier_has_fallbacks_behind_the_primary():
    """A single-entry tier is a pin wearing a router's clothes — no failover when the primary is
    rate-limited or erroring."""
    thin = {t: m for t, m in routing.TIERS.items() if len(m) < 2}
    assert not thin, f"tiers with no fallback: {thin}"


def test_tiers_span_more_than_one_provider():
    """Cross-provider failover is the point: an all-Anthropic tier still fails as one unit."""
    for tier, models in routing.TIERS.items():
        providers = {m.split("/")[0] for m in models}
        assert len(providers) > 1, f"{tier} is single-provider: {models}"
