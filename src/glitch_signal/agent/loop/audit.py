"""Routing audit (ROUTER self-monitoring) — data-grounded drift + fallback detection.

Reads `usage_events` (the durable per-model cost/volume record — cross-worker, unlike the in-process
routing metrics) and flags real anomalies for a human:

  (a) **primary_not_serving** — a tier whose PRIMARY model had no calls while a FALLBACK did. Because
      the loop sends OpenRouter a `models` array and OpenRouter fails over on runtime errors, a
      fallback carrying the traffic means the primary was degraded/rate-limited.
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

    # (a) fallback firing per tier
    for tier, models in routing.TIERS.items():
        primary, fallbacks = models[0], models[1:]
        if (by_model.get(primary, {}).get("recent_calls", 0)) == 0:
            active = [m for m in fallbacks if by_model.get(m, {}).get("recent_calls", 0) > 0]
            if active:
                findings.append({"type": "primary_not_serving", "tier": tier, "primary": primary,
                                 "active_fallbacks": active,
                                 "note": f"{tier} primary {primary} had 0 calls in {days}d while "
                                         f"fallback(s) served — primary may be degraded/rate-limited."})

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
