"""Allowlisted capability registry for AGENT-CRON `capability` payloads.

A `capability` job runs a specific internal coroutine directly — no agent/model turn. Only names in
this registry can be scheduled, so a job can never invoke arbitrary code. Each returns a small
summary dict recorded on the `scheduled_runs` row.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

CapFn = Callable[[str, dict], Awaitable[dict]]  # (brand_id, args) -> summary


async def _cap_curate(brand_id: str, args: dict) -> dict:
    """AGENT-LEARN: distill recent episodes into durable lessons."""
    from glitch_signal.agent.learn import curate

    return await curate(brand_id, limit=int(args.get("limit", 20)))


async def _cap_drive_scout(brand_id: str, args: dict) -> dict:
    """Run the drive_footage pipeline for one signal (awaited, so the run captures completion)."""
    from glitch_signal.agent.graph import get_graph
    from glitch_signal.config import brand_config

    if brand_config(brand_id).get("content_source") != "drive_footage":
        return {"skipped": "brand content_source is not drive_footage"}
    state = {
        "brand_id": brand_id,
        "content_source": "drive_footage",
        "signal_id": args.get("signal_id", ""),
        "platform": args.get("platform", "tiktok"),
        "retry_count": 0,
    }
    await get_graph().ainvoke(state)
    return {"ran": "drive_scout", "platform": state["platform"]}


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


_REGISTRY: dict[str, CapFn] = {
    "curate": _cap_curate,
    "drive_scout": _cap_drive_scout,
    "reconcile": _cap_reconcile,
    "routing_audit": _cap_routing_audit,
    "social_campaign": _cap_social_campaign,
    "social_reconcile": _cap_social_reconcile,
}


# SCOPE containment for self-scheduled `capability` jobs (#195). The clamp that stops a run from
# widening its own powers used to cover `agentTurn` only, so a `chat`-scoped run could pre-arm a
# capability that fires later with powers it never had. Each entry is the capability set (see
# `agent.loop.scopes.CAPABILITIES`) a job must already hold to be allowed to schedule it; an empty
# set means read-only/account-level bookkeeping that grants nothing new.
REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "curate": frozenset({"memory"}),
    "drive_scout": frozenset({"media"}),
    "reconcile": frozenset(),
    "routing_audit": frozenset(),
    "social_campaign": frozenset({"media", "publish"}),
    "social_reconcile": frozenset(),
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
