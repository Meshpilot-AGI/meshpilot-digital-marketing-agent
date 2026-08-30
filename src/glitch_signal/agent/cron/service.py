"""The scheduler tick + payload dispatch for AGENT-CRON.

`sweep()` is called from the per-worker scheduler loop. It claims due jobs (exactly-once via the
store's SKIP-LOCKED claim) and dispatches each payload in the background. The global
`agent_cron_enabled` kill-switch gates the whole thing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from glitch_signal.agent.cron import capabilities, runctx, store

log = structlog.get_logger(__name__)

CRON_SWEEP_INTERVAL_S = 20      # don't sweep on every fast scheduler tick
CRON_CLAIM_LIMIT = 20           # max jobs claimed per sweep
CAPABILITY_TIMEOUT_S = 600      # hard cap on a capability payload

_last_sweep: datetime | None = None


def _enabled() -> bool:
    from glitch_signal.config import settings

    return bool(getattr(settings(), "agent_cron_enabled", False))


def _max_failures() -> int:
    from glitch_signal.config import settings

    return int(getattr(settings(), "agent_cron_max_failures", 3))


async def sweep(*, now: datetime | None = None, engine=None) -> int:
    """Claim + dispatch due jobs. Returns how many were dispatched. Safe to call every tick."""
    global _last_sweep
    if not _enabled():
        return 0
    now = now or datetime.now(timezone.utc)
    if _last_sweep and (now - _last_sweep).total_seconds() < CRON_SWEEP_INTERVAL_S:
        return 0
    _last_sweep = now

    claimed = await store.claim_due(now, CRON_CLAIM_LIMIT, engine=engine)
    for job in claimed:
        asyncio.create_task(_dispatch(job, engine=engine))
    if claimed:
        log.info("cron.sweep", claimed=len(claimed))
    return len(claimed)


async def run_now(job_id: str, *, brand_id: str | None = None, engine=None) -> str | None:
    """Force one run of a job immediately, out-of-band — does NOT touch its natural next slot.

    `brand_id`, when given, scopes the lookup to that brand (#95). Returns the opened run_id, or None
    if the job is unknown/not that brand's. Ignores the kill-switch (operator action).
    """
    job = await store.get_job(job_id, brand_id=brand_id, with_runs=0, engine=engine)
    if job is None:
        return None
    run_id = await store.open_run(job_id, job["brand_id"], engine=engine)
    dispatch_job = {**job, "run_id": run_id}
    asyncio.create_task(_dispatch(dispatch_job, engine=engine))
    return run_id


async def _dispatch(job: dict, *, engine=None) -> None:
    """Run one claimed job's payload and finalize its run. Never raises out of the task."""
    run_id = job["run_id"]
    job_id = job["id"]
    brand = job["brand_id"]
    # Make this job the pacing target for any next_check the payload calls.
    runctx.current_job_id.set(job_id)
    runctx.current_job_pacing.set(job.get("pacing") or {})
    try:
        if job["payload_kind"] == "agentTurn":
            result = await _run_agent_turn(brand, job["payload"])
        elif job["payload_kind"] == "pipelineTurn":
            result = await _run_pipeline_turn(brand, job["payload"])
        elif job["payload_kind"] == "capability":
            result = await _run_capability(brand, job["payload"])
        else:
            raise ValueError(f"unknown payload_kind {job['payload_kind']!r}")
        await store.finish_run(run_id, job_id, status="done", result=result,
                               delete_after_run=bool(job.get("delete_after_run")),
                               max_failures=_max_failures(), engine=engine)
    except Exception as exc:  # noqa: BLE001 — a job failure is recorded, never crashes the sweep
        log.warning("cron.job_failed", job_id=job_id, error=str(exc)[:200])
        await store.finish_run(run_id, job_id, status="error", error=str(exc),
                               delete_after_run=bool(job.get("delete_after_run")),
                               max_failures=_max_failures(), engine=engine)


async def _run_pipeline_turn(brand: str, payload: dict) -> dict:
    """Run a scheduled PIPELINE occurrence by RE-RESOLVING the pipeline at fire time.

    The cron job stores only the pipeline name, so scope/goal and the required kill-switches are read
    live from the registry every occurrence — a discovery schedule stays inert while
    `agent_discovery_enabled` is off, and content honors the current `agent_content_media_enabled`
    (paid media on/off) instead of a value frozen at seed time. If a requirement is unmet the run is
    SKIPPED (recorded, not executed), mirroring the manual endpoint's 409."""
    from glitch_signal.agent.loop import pipelines

    p = pipelines.resolve(str(payload.get("pipeline", "")))
    if p is None:
        raise ValueError(f"unknown pipeline {payload.get('pipeline')!r}")
    missing = p.missing_requirements()
    if missing:
        return {"pipeline": p.name, "skipped": f"requires: {', '.join(missing)}"}
    return await _run_agent_turn(
        brand, {"goal": p.render_goal(brand), "scope": p.scope, "max_steps": p.max_steps})


async def _run_agent_turn(brand: str, payload: dict) -> dict:
    """Run the agent loop on a goal, persisting an agent_runs row like the manual endpoint."""
    import uuid as _uuid

    from glitch_signal.agent.loop import run as agent_run
    from glitch_signal.agent.loop import runs as run_store

    goal = str(payload.get("goal", "")).strip()
    if not goal:
        raise ValueError("agentTurn payload requires a goal")
    max_steps = int(payload.get("max_steps", 5))
    from glitch_signal.config import settings as _settings
    scope = str(payload.get("scope") or _settings().agent_default_scope)  # SCOPE: job toolset (clamped at create)
    agent_run_id = _uuid.uuid4().hex
    await run_store.create_run(agent_run_id, brand, goal)
    try:
        res = await agent_run(brand, goal, max_steps=max_steps, scope=scope)
        await run_store.finish_run(agent_run_id, res)
        return {"run_id": agent_run_id, "steps": res.get("steps")}
    except Exception as exc:
        await run_store.fail_run(agent_run_id, str(exc))
        raise


async def _run_capability(brand: str, payload: dict) -> dict:
    name = str(payload.get("name", ""))
    fn = capabilities.get(name)
    if fn is None:
        raise ValueError(f"unknown capability {name!r}; allowed: {capabilities.names()}")
    return await asyncio.wait_for(fn(brand, payload.get("args", {}) or {}), timeout=CAPABILITY_TIMEOUT_S)
