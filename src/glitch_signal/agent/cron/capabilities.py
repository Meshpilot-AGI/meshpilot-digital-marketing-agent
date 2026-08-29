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
    """Balance-delta cost reconciliation — hook; body lands in COST-METER INC-2."""
    return {"status": "not_implemented", "note": "reconcile body delivered by COST-METER INC-2"}


_REGISTRY: dict[str, CapFn] = {
    "curate": _cap_curate,
    "drive_scout": _cap_drive_scout,
    "reconcile": _cap_reconcile,
}


def names() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str) -> CapFn | None:
    return _REGISTRY.get(name)
