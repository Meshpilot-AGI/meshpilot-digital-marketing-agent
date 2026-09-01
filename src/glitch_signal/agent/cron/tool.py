"""The `schedule` loop capability-tool — how the agent schedules its OWN future work.

Self-scoped: an agent-owned job is stamped `owner = agent:<brand>`, and `list`/`cancel` only ever
see or touch jobs with that owner, so one brand's agent can never read or cancel another's (or the
operator's) jobs. `create` respects the global kill-switch and a per-brand creator-cap. `next_check`
re-paces the job currently executing (from the run context), clamped to its pacing bounds.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from glitch_signal.agent.cron import capabilities, runctx, store

_DUR = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_UNIT_MS = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def _owner(brand_id: str) -> str:
    return f"agent:{brand_id}"


def parse_duration_ms(value: str) -> int:
    m = _DUR.match(str(value))
    if not m:
        raise ValueError(f"bad duration {value!r} (use e.g. 30s, 15m, 2h, 1d)")
    return int(m.group(1)) * _UNIT_MS[m.group(2).lower()]


def _cron_enabled() -> bool:
    from glitch_signal.config import settings

    return bool(getattr(settings(), "agent_cron_enabled", False))


def _max_jobs() -> int:
    from glitch_signal.config import settings

    return int(getattr(settings(), "agent_cron_max_jobs_per_brand", 20))


def _clamp_scope(payload_kind: str, payload: dict) -> str | None:
    """Contain a self-scheduled job to the creating run's scope. Returns a refusal reason, or None.

    `agentTurn` carries a scope name, so an over-broad one is silently CLAMPED down (the job still
    runs, just with fewer tools). `pipelineTurn` and `capability` have no scope of their own — their
    powers are fixed by the pipeline/registry entry — so containment can only be enforced by
    REFUSING to create the job.
    """
    from glitch_signal.agent.loop import scopes

    current = scopes.current()
    if payload_kind == "agentTurn":
        if not scopes.is_subset(payload.get("scope"), current):
            payload["scope"] = current
        return None

    if payload_kind == "pipelineTurn":
        from glitch_signal.agent.loop import pipelines

        p = pipelines.resolve(str(payload.get("pipeline", "")))
        if p is None:
            return f"unknown pipeline {payload.get('pipeline')!r}"
        if not scopes.is_subset(p.scope, current):
            return (f"scope escalation: pipeline {p.name!r} needs scope {p.scope!r}, "
                    f"which is not within this run's {current!r} scope")
        return None

    if payload_kind == "capability":
        name = str(payload.get("name", ""))
        needed = capabilities.required_capabilities(name)
        if name not in capabilities.names():
            return f"unknown capability {name!r}; allowed: {capabilities.names()}"
        if not scopes.grants(current, needed):
            missing = sorted(needed - scopes.capabilities_of(current))
            return (f"scope escalation: capability {name!r} needs {missing}, "
                    f"not granted by this run's {current!r} scope")
        return None

    return f"unknown payload_kind {payload_kind!r}"


async def schedule_tool(args: dict, brand_id: str) -> str:
    """Dispatch a `schedule` action for the active brand. Returns a concise observation string."""
    action = str(args.get("action", "")).lower()
    owner = _owner(brand_id)

    if action == "create":
        if not _cron_enabled():
            return "ERROR: self-scheduling is disabled (agent_cron_enabled is off)"
        active = await store.count_active_owned(brand_id, owner)
        if active >= _max_jobs():
            return f"ERROR: creator-cap reached ({active}/{_max_jobs()} active jobs); cancel one first"
        payload = dict(args.get("payload", {}) or {})
        # SCOPE anti-escalation: a self-scheduled job may never exceed the CURRENT run's scope.
        # This has to cover EVERY payload kind (#195) — a deferred `capability`/`pipelineTurn` job
        # widens powers across time just as effectively as an over-scoped agentTurn, and it fires
        # long after the run that armed it is gone.
        denied = _clamp_scope(str(args.get("payload_kind", "")), payload)
        if denied:
            return f"ERROR: {denied}"
        try:
            job_id = await store.create_job(
                brand_id=brand_id, owner=owner,
                name=str(args["name"]),
                schedule_kind=str(args["schedule_kind"]),
                schedule=args["schedule"],
                payload_kind=str(args["payload_kind"]),
                payload=payload,
                pacing=args.get("pacing") or {},
                delete_after_run=bool(args.get("delete_after_run", args.get("schedule_kind") == "at")),
                now=datetime.now(timezone.utc),
            )
        except KeyError as e:
            return f"ERROR: missing field {e}"
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {str(e)[:200]}"
        return f"scheduled job {job_id} ({args['name']})"

    if action == "list":
        jobs = await store.list_jobs(brand_id, owner=owner)
        return json.dumps([
            {"id": j["id"], "name": j["name"], "enabled": j["enabled"],
             "schedule_kind": j["schedule_kind"], "payload_kind": j["payload_kind"],
             "next_run_at": str(j.get("next_run_at"))}
            for j in jobs
        ]) or "[]"

    if action == "cancel":
        ok = await store.delete_job(str(args.get("id", "")), owner=owner)
        return "cancelled" if ok else "ERROR: no such job owned by you"

    if action == "next_check":
        job_id = runctx.current_job_id.get()
        if not job_id:
            return "ERROR: next_check is only valid inside a scheduled agentTurn run"
        try:
            ms = parse_duration_ms(args.get("in", ""))
        except ValueError as e:
            return f"ERROR: {e}"
        pacing = runctx.current_job_pacing.get() or {}
        lo = int(pacing.get("min_ms", 0) or 0)
        hi = int(pacing.get("max_ms", 0) or 0)
        if lo and ms < lo:
            ms = lo
        if hi and ms > hi:
            ms = hi
        next_at = datetime.now(timezone.utc) + timedelta(milliseconds=ms)
        await store.set_next_run(job_id, next_at, brand_id=brand_id)  # scope to the caller's brand (#95)
        return f"next check set for {next_at.isoformat()}"

    return f"ERROR: unknown action {action!r} (create|list|cancel|next_check)"
