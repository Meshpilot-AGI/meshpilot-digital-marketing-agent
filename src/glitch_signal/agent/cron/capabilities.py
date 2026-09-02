"""Allowlisted capability registry for AGENT-CRON `capability` payloads.

A `capability` job runs a specific internal coroutine directly — no agent/model turn. Only names in
this registry can be scheduled, so a job can never invoke arbitrary code. Each returns a small
summary dict recorded on the `scheduled_runs` row.
"""
from __future__ import annotations

from typing import Awaitable, Callable

CapFn = Callable[[str, dict], Awaitable[dict]]  # (brand_id, args) -> summary


async def _cap_curate(brand_id: str, args: dict) -> dict:
    """AGENT-LEARN: distill recent episodes into durable lessons."""
    from glitch_signal.agent.learn import curate

    return await curate(brand_id, limit=int(args.get("limit", 20)))



async def _cap_reconcile(brand_id: str, args: dict) -> dict:
    """Balance-delta cost reconciliation across credit vendors (COST-METER INC-2).

    Account-level, not per-brand (vendors have no per-tenant balance), so `brand_id` is ignored.
    """
    from glitch_signal.analytics.cost import reconcile

    return await reconcile.run(args.get("vendors"))


async def _cap_routing_audit(brand_id: str, args: dict) -> dict:
    """ROUTER self-monitoring: flag primary-not-serving (fallback firing) + cost/call drift from
    usage_events. Account-level (not per-brand), so `brand_id` is ignored."""
    from glitch_signal.agent.loop.audit import routing_audit

    res = await routing_audit(days=int(args.get("days", 1)),
                              baseline_days=int(args.get("baseline_days", 7)))
    return {"summary": res["summary"], "findings": res["findings"]}


async def _cap_social_campaign(brand_id: str, args: dict) -> dict:
    """AGENT-SOCIAL: run one social_campaign cycle (ideate → media → captions → fan-out)."""
    from glitch_signal.agent.social.campaign import run_campaign

    res = await run_campaign(brand_id)
    return {"ran": "social_campaign", "brand": brand_id,
            "posted": sum(1 for p in getattr(res, "posts", []) if p.status == "posted"),
            "skipped_reason": getattr(res, "skipped_reason", None)}


async def _cap_social_reconcile(brand_id: str, args: dict) -> dict:
    """AGENT-SOCIAL: settle Buffer submissions still sitting `pending` in the social outbox.

    Account-level (the sweep is keyed on post age, not brand), so `brand_id` is ignored. Also runs
    automatically from the cron sweep — this entry exists so it can be forced out-of-band.
    """
    from glitch_signal.agent.social.reconcile import reconcile_pending

    return await reconcile_pending()


async def _cap_social_outcomes(brand_id: str, args: dict) -> dict:
    """AGENT-SOCIAL: read back per-post performance for any reading that is due.

    Account-level (the sweep is keyed on post age, not brand), so `brand_id` is ignored. Also runs
    from the cron sweep — this entry exists so it can be forced out-of-band.
    """
    from glitch_signal.agent.social.outcomes import collect

    return await collect()


async def _cap_learn_performance(brand_id: str, args: dict) -> dict:
    """AGENT-LEARN: revise strategy from MEASURED post performance.

    Distinct from `curate`, which distils the agent's own episodes — this one reads outcomes. It
    declines explicitly (`wrote: 0`) until enough posts exist per cell to support a conclusion, and
    that refusal is the expected result for most of the loop's life.
    """
    from glitch_signal.agent.learn.outcomes import curate_performance

    return await curate_performance(brand_id)


_REGISTRY: dict[str, CapFn] = {
    "curate": _cap_curate,
    "reconcile": _cap_reconcile,
    "routing_audit": _cap_routing_audit,
    "social_campaign": _cap_social_campaign,
    "social_reconcile": _cap_social_reconcile,
    "social_outcomes": _cap_social_outcomes,
    "learn_performance": _cap_learn_performance,
}


# SCOPE containment for self-scheduled `capability` jobs (#195). The clamp that stops a run from
# widening its own powers used to cover `agentTurn` only, so a `chat`-scoped run could pre-arm a
# capability that fires later with powers it never had. Each entry is the capability set (see
# `agent.loop.scopes.CAPABILITIES`) a job must already hold to be allowed to schedule it; an empty
# set means read-only/account-level bookkeeping that grants nothing new.
REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "curate": frozenset({"memory"}),
    "reconcile": frozenset(),
    "routing_audit": frozenset(),
    "social_campaign": frozenset({"media", "publish"}),
    "social_reconcile": frozenset(),
    "social_outcomes": frozenset(),
    "learn_performance": frozenset({"memory"}),
}


def required_capabilities(name: str) -> frozenset[str]:
    """Capabilities a scheduler must already hold to schedule `name`.

    An UNKNOWN capability returns the full capability set, so a name we don't recognise fails
    containment rather than sailing through unchecked.
    """
    from glitch_signal.agent.loop import scopes

    if name not in _REGISTRY:
        return frozenset(scopes.CAPABILITIES)
    return REQUIRED_CAPABILITIES.get(name, frozenset(scopes.CAPABILITIES))


def names() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str) -> CapFn | None:
    return _REGISTRY.get(name)
