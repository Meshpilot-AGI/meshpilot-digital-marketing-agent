"""Per-brand spend budget + steps ceiling (COST-METER INC-3).

Enforces two guards on the self-metered spend from INC-1/2:
  * a per-brand DAILY USD cap — agent runs and paid media are denied once today's metered spend
    reaches the cap (0 = unlimited; per-brand override via brand_env("DAILY_BUDGET_USD")),
  * a hard ceiling on agent-loop `max_steps` (clamps any caller/payload value).

Fail-OPEN on error: a metering/DB failure must never block legitimate work — a broken meter should
not become an outage. The cap only ever denies when we can positively read spend at/over it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def steps_ceiling() -> int:
    from glitch_signal.config import settings

    return max(1, int(getattr(settings(), "agent_max_steps_ceiling", 12)))


def clamp_steps(max_steps: int) -> int:
    """Clamp a requested step count to [1, ceiling] (COST-METER INC-3, closes the unbounded-steps hole)."""
    try:
        n = int(max_steps)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(n, steps_ceiling()))


def brand_daily_cap(brand_id: str) -> float:
    """Per-brand daily USD cap: brand_env override wins, else the global default. 0 = unlimited."""
    from glitch_signal.config import brand_env, settings

    override = brand_env("DAILY_BUDGET_USD", brand_id)
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return float(getattr(settings(), "agent_brand_daily_budget_usd", 0.0) or 0.0)


def _day_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


async def budget_status(brand_id: str, *, now: datetime | None = None, engine: Any | None = None) -> dict:
    """Today's spend vs the brand's cap. Never raises — returns over=False on any read failure."""
    from glitch_signal.analytics.cost.meter import spend_summary

    cap = brand_daily_cap(brand_id)
    start, end = _day_window(now)
    try:
        summary = await spend_summary(brand_id, start, end, engine=engine)
        spent = float(summary.get("total_usd", 0.0))
    except Exception:  # noqa: BLE001 — fail-open: a broken meter never blocks work
        return {"brand_id": brand_id, "cap_usd": cap, "spent_usd": None, "over": False,
                "unlimited": cap <= 0, "error": "spend read failed"}
    over = cap > 0 and spent >= cap
    return {
        "brand_id": brand_id,
        "cap_usd": cap,
        "spent_usd": round(spent, 6),
        "remaining_usd": round(cap - spent, 6) if cap > 0 else None,
        "pct": round(spent / cap, 4) if cap > 0 else None,
        "unlimited": cap <= 0,
        "over": over,
    }


async def check(brand_id: str, *, now: datetime | None = None, engine: Any | None = None) -> tuple[bool, str]:
    """(allowed, reason) — deny an expensive action when the brand is at/over its daily cap."""
    status = await budget_status(brand_id, now=now, engine=engine)
    if status["over"]:
        return False, (f"brand {brand_id} over daily budget "
                       f"(${status['spent_usd']:.4f} / ${status['cap_usd']:.2f})")
    return True, ""
