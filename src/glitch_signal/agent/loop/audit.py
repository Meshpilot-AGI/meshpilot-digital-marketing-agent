"""Routing audit (ROUTER self-monitoring) — data-grounded drift + fallback detection.

Reads `usage_events` (the durable per-model cost/volume record — cross-worker, unlike the in-process
routing metrics) and flags real anomalies for a human:

  (a) **primary_idle** (severity: info) — a tier whose PRIMARY model had no calls while a FALLBACK did.
      This is a SOFT signal, not a verdict: `usage_events` records only the served model, not the
      requested tier, so the fallback may have served because the primary was degraded/rate-limited OR
      because a caller pinned it directly (e.g. a content env override). Flagged for a human to verify.
  (b) **cost_per_call_drift** — a model whose recent cost-per-call is well above its own baseline.

No ML, no "auto-tuning" of thresholds — just anomalies grounded in actual usage. Run nightly via the
`routing_audit` cron capability, or on demand via GET /internal/agent/routing/audit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

_Q = text(
    "SELECT model, "
    "  count(*) FILTER (WHERE created_at >= :recent_from) AS recent_calls, "
    "  coalesce(sum(cost_usd) FILTER (WHERE created_at >= :recent_from), 0) AS recent_cost, "
    "  count(*) FILTER (WHERE created_at < :recent_from) AS base_calls, "
    "  coalesce(sum(cost_usd) FILTER (WHERE created_at < :recent_from), 0) AS base_cost "
    "FROM usage_events "
    "WHERE vendor = 'openrouter' AND model IS NOT NULL AND created_at >= :base_from "
    "GROUP BY model"
)


async def routing_audit(*, days: int = 1, baseline_days: int = 7, drift_ratio: float = 1.5,
                        min_calls: int = 5, engine: Any = None) -> dict:
    """Audit per-model usage over the last `days` vs the prior `baseline_days`. Returns
    {summary, findings, by_model}. Fail-soft on a DB error (returns an error field, never raises)."""
    from glitch_signal.agent.loop import routing
    from glitch_signal.db.session import _engine

    now = datetime.now(timezone.utc)
    recent_from = now - timedelta(days=days)
    base_from = now - timedelta(days=days + baseline_days)
    eng = engine or _engine()
    try:
        async with eng.connect() as c:
            rows = (await c.execute(_Q, {"recent_from": recent_from, "base_from": base_from})).mappings().all()
    except Exception as exc:  # noqa: BLE001 — audit is monitoring, must never break a run
        log.warning("agent.routing.audit_failed", error=str(exc)[:200])
        return {"summary": {"error": str(exc)[:200]}, "findings": [], "by_model": {}}

    by_model = {r["model"]: {"recent_calls": int(r["recent_calls"] or 0),
                             "recent_cost": float(r["recent_cost"] or 0),
                             "base_calls": int(r["base_calls"] or 0),
                             "base_cost": float(r["base_cost"] or 0)} for r in rows}
    findings: list[dict] = []

    # (a) fallback firing per tier — uses the EFFECTIVE (override-aware) tier list. This is a SOFT
    #     signal: usage_events records only the served model, not the requested tier, so a fallback
    #     model may have served because the primary failed OR because a caller pinned it directly
    #     (e.g. a content env override). Flagged as informational for a human to check, not a verdict.
    for tier in routing.TIERS:
        models = routing.resolve(tier)
        primary, fallbacks = models[0], models[1:]
        if (by_model.get(primary, {}).get("recent_calls", 0)) == 0:
            active = [m for m in fallbacks if by_model.get(m, {}).get("recent_calls", 0) > 0]
            if active:
                findings.append({"type": "primary_idle", "severity": "info", "tier": tier,
                                 "primary": primary, "active_models_in_tier": active,
                                 "note": f"{tier} primary {primary} had 0 calls in {days}d while other "
                                         f"tier models served — the primary MAY be degraded, or those "
                                         f"models were pinned directly. Verify against provider status."})

    # (b) cost-per-call drift
    for model, r in by_model.items():
        if r["recent_calls"] >= min_calls and r["base_calls"] >= min_calls:
            r_cpc = r["recent_cost"] / r["recent_calls"]
            b_cpc = r["base_cost"] / r["base_calls"]
            if b_cpc > 0 and r_cpc > b_cpc * drift_ratio:
                findings.append({"type": "cost_per_call_drift", "model": model,
                                 "recent_cost_per_call": round(r_cpc, 6),
                                 "baseline_cost_per_call": round(b_cpc, 6),
                                 "ratio": round(r_cpc / b_cpc, 2)})

    summary = {"window_days": days, "baseline_days": baseline_days,
               "models_seen": len(by_model), "findings": len(findings)}
    (log.warning if findings else log.info)("agent.routing.audit", **summary, detail=findings[:10])
    return {"summary": summary, "findings": findings, "by_model": by_model}
