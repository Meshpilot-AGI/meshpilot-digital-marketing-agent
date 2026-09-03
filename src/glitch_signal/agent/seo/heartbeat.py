"""Alerting on the GAP between SEO cycles (SEO-9).

`seo_cycle` made a failure queryable. Nobody queries it. This is what turns "you could have noticed"
into "you were told".

**The thing being watched is silence, not an error.** A cycle that crashes logs a row with
`ok=False`; a cycle that never runs at all — laptop asleep, launchd unloaded, plist broken, the Mac
simply off — logs nothing, and nothing is exactly what a quiet, healthy day looks like. So the signal
is the AGE of the newest row, and no row at all is the loudest case rather than a missing one.

⚠️ **This runs in the CLOUD, not on the Mac.** A watcher living on the machine it watches dies with
it, and reports nothing at precisely the moment there is something to report. It needs only the
database, so the agent's own cron can host it.

⚠️ **It must never write to `seo_cycle`.** Recording its own run there would refresh the newest-row
timestamp and mask the very gap it exists to measure — the watcher would permanently reassure itself.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# The cycle runs daily. A gap longer than a day plus slack means a run was missed, not late.
DEFAULT_MAX_GAP_HOURS = 30.0

# One alert per this window per brand. The check runs on its own schedule, so without this a single
# stale cycle would page every time the watcher fires — and an alert that repeats is an alert people
# filter.
_ALERT_EVERY_S = 43200.0   # 12h


def _cfg(brand_id: str, name: str, default: str = "") -> str:
    from glitch_signal.config import brand_env

    return brand_env(f"SEO_{name}", brand_id, default) or default


async def check(brand_id: str, *, max_gap_hours: float = DEFAULT_MAX_GAP_HOURS,
                now: dt.datetime | None = None, notify: Any = None,
                engine: Any = None) -> dict:
    """Is the cycle still running? Alerts once per window when it is not.

    Returns a summary rather than raising: this is a monitor, and a monitor that fails its own run
    tells you nothing about the thing it monitors.
    """
    from glitch_signal.agent.seo import track

    now = now or dt.datetime.now(dt.UTC)
    rows = await track.recent_cycles(brand_id, limit=1, engine=engine)

    if not rows:
        # Not a missing datapoint — the loudest case there is. Either it has never run, or every row
        # predates the table.
        return await _raise_alarm(brand_id, reason="no SEO cycle has ever been recorded",
                                  age_hours=None, last=None, notify=notify)

    last = rows[0]
    ran_at = last.get("ran_at")
    if isinstance(ran_at, dt.datetime) and ran_at.tzinfo is None:
        ran_at = ran_at.replace(tzinfo=dt.UTC)
    age_hours = (now - ran_at).total_seconds() / 3600.0 if ran_at else None

    if age_hours is not None and age_hours <= max_gap_hours:
        log.info("seo.heartbeat_ok", brand_id=brand_id, age_hours=round(age_hours, 1),
                 last_outcome=last.get("outcome"))
        return {"ok": True, "stale": False, "age_hours": round(age_hours, 1),
                "last_outcome": last.get("outcome"), "alerted": False}

    return await _raise_alarm(
        brand_id,
        reason=(f"no SEO cycle in {age_hours:.1f}h (threshold {max_gap_hours:g}h)"
                if age_hours is not None else "the last cycle has no timestamp"),
        age_hours=age_hours, last=last, notify=notify)


async def _raise_alarm(brand_id: str, *, reason: str, age_hours: float | None,
                       last: dict | None, notify: Any) -> dict:
    """Log loudly always; email at most once per window."""
    log.warning("seo.heartbeat_stale", brand_id=brand_id, reason=reason,
                last_outcome=(last or {}).get("outcome"))
    out = {"ok": True, "stale": True, "reason": reason, "alerted": False,
           "age_hours": round(age_hours, 1) if age_hours is not None else None,
           "last_outcome": (last or {}).get("outcome")}

    to = _cfg(brand_id, "ALERT_EMAIL")
    if not to:
        out["detail"] = "no <PREFIX>_SEO_ALERT_EMAIL configured — logged only"
        return out

    if not await _may_alert(brand_id):
        out["detail"] = "already alerted within the window"
        return out

    body = (f"The SEO cycle for {brand_id} appears to have stopped.\n\n"
            f"{reason}.\n\n"
            f"Last recorded outcome: {(last or {}).get('outcome') or 'none'}\n"
            f"Last run: {(last or {}).get('ran_at') or 'never'}\n\n"
            f"The cycle is a launchd job on the operator's Mac; the usual causes are the machine "
            f"being asleep or off, or the job being unloaded. Check with:\n"
            f"  launchctl list | grep meshpilot\n"
            f"  tail /tmp/meshpilot-seo-cycle.log\n")
    try:
        send = notify or _default_notify
        await send(brand_id=brand_id, to=to, subject=f"[MeshPilot] SEO cycle stalled — {brand_id}",
                   text=body)
        out["alerted"] = True
    except Exception as exc:  # noqa: BLE001 — a monitor must not die on its own delivery
        log.warning("seo.heartbeat_alert_failed", error=str(exc)[:200])
        out["detail"] = f"alert delivery failed: {str(exc)[:120]}"
    return out


async def _may_alert(brand_id: str) -> bool:
    """One alert per window. An alert that repeats every hour is an alert people filter."""
    try:
        from glitch_signal.middleware.shared_state import SharedWindowLimiter

        allowed, _ = await SharedWindowLimiter(1, _ALERT_EVERY_S).check(f"seo-alert:{brand_id}")
        return bool(allowed)
    except Exception:  # noqa: BLE001 — if the limiter is unavailable, alerting beats silence
        return True


async def _default_notify(**kw: Any) -> str:
    from glitch_signal.comms.email import send_email

    return await send_email(**kw)
