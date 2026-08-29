"""Durable job + run store for AGENT-CRON.

`claim_due` is the concurrency core: it selects due jobs `FOR UPDATE SKIP LOCKED`, advances each
job's `next_run_at` (or spends a one-shot) and inserts a `scheduled_runs` row — all in one
transaction, so across N workers each due job is claimed exactly once. The lock is released on
commit, before the (potentially long) payload runs. Everything else is ordinary CRUD.

The SQLAlchemy engine is injectable so the CRUD/finish logic unit-tests without a real DB; the
SKIP-LOCKED exactly-once guarantee is a Postgres property, asserted in the live check.
"""
from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from glitch_signal.agent.cron import schedule as sched
from glitch_signal.db.session import _engine

_JSON_COLS = ("schedule", "payload", "pacing", "result")

_INSERT_JOB = text(
    "INSERT INTO scheduled_jobs "
    "(brand_id, name, owner, enabled, schedule_kind, schedule, payload_kind, payload, "
    " next_run_at, pacing, delete_after_run) "
    "VALUES (:brand_id, :name, :owner, :enabled, :schedule_kind, cast(:schedule as jsonb), "
    " :payload_kind, cast(:payload as jsonb), :next_run_at, cast(:pacing as jsonb), :delete_after_run) "
    "RETURNING id"
)
_SELECT_DUE = text(
    "SELECT id, brand_id, name, owner, schedule_kind, schedule, payload_kind, payload, "
    " delete_after_run, pacing "
    "FROM scheduled_jobs "
    "WHERE enabled AND next_run_at IS NOT NULL AND next_run_at <= :now "
    "ORDER BY next_run_at FOR UPDATE SKIP LOCKED LIMIT :limit"
)
_ADVANCE = text(
    "UPDATE scheduled_jobs SET next_run_at=:next, last_run_at=:now, updated_at=now() WHERE id=:id"
)
_SPEND_ONESHOT = text(
    "UPDATE scheduled_jobs SET next_run_at=NULL, enabled=false, last_run_at=:now, updated_at=now() "
    "WHERE id=:id"
)
_INSERT_RUN = text(
    "INSERT INTO scheduled_runs (id, job_id, brand_id, status) VALUES (:id, :job_id, :brand_id, 'running')"
)
_FINISH_RUN = text(
    "UPDATE scheduled_runs SET status=:status, result=cast(:result as jsonb), error=:error, "
    "finished_at=now() WHERE id=:id"
)
_ON_SUCCESS = text("UPDATE scheduled_jobs SET fail_count=0, updated_at=now() WHERE id=:id")
_ON_ERROR = text(
    "UPDATE scheduled_jobs SET fail_count=fail_count+1, "
    "enabled = CASE WHEN fail_count+1 >= :max THEN false ELSE enabled END, "
    "disabled_reason = CASE WHEN fail_count+1 >= :max THEN :reason ELSE disabled_reason END, "
    "updated_at=now() WHERE id=:id"
)
_DELETE_JOB = text("DELETE FROM scheduled_jobs WHERE id=:id")
_DELETE_JOB_SCOPED = text("DELETE FROM scheduled_jobs WHERE id=:id AND owner=:owner RETURNING id")
_GET_JOB = text("SELECT * FROM scheduled_jobs WHERE id=:id")
_LIST_ALL = text("SELECT * FROM scheduled_jobs WHERE brand_id=:brand ORDER BY created_at DESC")
_LIST_OWNED = text(
    "SELECT * FROM scheduled_jobs WHERE brand_id=:brand AND owner=:owner ORDER BY created_at DESC"
)
_COUNT_OWNED = text(
    "SELECT count(*) AS n FROM scheduled_jobs WHERE brand_id=:brand AND owner=:owner AND enabled"
)
_RECENT_RUNS = text(
    "SELECT id, status, result, error, started_at, finished_at FROM scheduled_runs "
    "WHERE job_id=:job_id ORDER BY started_at DESC LIMIT :limit"
)
_SET_NEXT = text("UPDATE scheduled_jobs SET next_run_at=:next, updated_at=now() WHERE id=:id")


def _decode(row: Any) -> dict:
    d = dict(row)
    for col in _JSON_COLS:
        v = d.get(col)
        if isinstance(v, str):
            try:
                d[col] = json.loads(v)
            except Exception:  # noqa: BLE001
                pass
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    if "job_id" in d and d["job_id"] is not None:
        d["job_id"] = str(d["job_id"])
    return d


async def create_job(*, brand_id: str, name: str, schedule_kind: str, schedule: dict,
                     payload_kind: str, payload: dict, owner: str = "operator",
                     pacing: dict | None = None, delete_after_run: bool = False,
                     enabled: bool = True, now: datetime, engine: Any | None = None) -> str:
    sched.validate(schedule, schedule_kind)
    next_run_at = sched.compute_first_run(schedule, schedule_kind, now=now)
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(_INSERT_JOB, {
            "brand_id": brand_id, "name": name, "owner": owner, "enabled": enabled,
            "schedule_kind": schedule_kind, "schedule": json.dumps(schedule),
            "payload_kind": payload_kind, "payload": json.dumps(payload),
            "next_run_at": next_run_at, "pacing": json.dumps(pacing or {}),
            "delete_after_run": delete_after_run,
        })).mappings().first()
    return str(row["id"])


async def claim_due(now: datetime, limit: int, *, engine: Any | None = None) -> list[dict]:
    """Claim up to `limit` due jobs (exactly-once across workers), advancing each and opening a run.

    Returns a list of dicts: the job fields the dispatcher needs + the opened `run_id`.
    """
    eng = engine or _engine()
    claimed: list[dict] = []
    async with eng.begin() as conn:
        rows = (await conn.execute(_SELECT_DUE, {"now": now, "limit": limit})).mappings().all()
        for r in rows:
            job = _decode(r)
            nxt = sched.compute_next(job["schedule"], job["schedule_kind"], now=now)
            if nxt is None:
                await conn.execute(_SPEND_ONESHOT, {"id": job["id"], "now": now})
            else:
                await conn.execute(_ADVANCE, {"id": job["id"], "next": nxt, "now": now})
            run_id = _uuid.uuid4().hex
            await conn.execute(_INSERT_RUN, {"id": run_id, "job_id": job["id"], "brand_id": job["brand_id"]})
            job["run_id"] = run_id
            claimed.append(job)
    return claimed


async def finish_run(run_id: str, job_id: str, *, status: str, result: dict | None = None,
                     error: str | None = None, delete_after_run: bool = False,
                     max_failures: int = 3, engine: Any | None = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_FINISH_RUN, {
            "id": run_id, "status": status,
            "result": json.dumps(result) if result is not None else None,
            "error": (error or None) and str(error)[:2000],
        })
        if status == "done":
            await conn.execute(_ON_SUCCESS, {"id": job_id})
            if delete_after_run:
                await conn.execute(_DELETE_JOB, {"id": job_id})
        elif status == "error":
            await conn.execute(_ON_ERROR, {"id": job_id, "max": max_failures,
                                           "reason": f"auto-disabled after {max_failures} failures"})


async def get_job(job_id: str, *, with_runs: int = 10, engine: Any | None = None) -> dict | None:
    eng = engine or _engine()
    async with eng.connect() as conn:
        row = (await conn.execute(_GET_JOB, {"id": job_id})).mappings().first()
        if row is None:
            return None
        job = _decode(row)
        if with_runs:
            runs = (await conn.execute(_RECENT_RUNS, {"job_id": job_id, "limit": with_runs})).mappings().all()
            job["recent_runs"] = [_decode(x) for x in runs]
    return job


async def list_jobs(brand_id: str, *, owner: str | None = None, engine: Any | None = None) -> list[dict]:
    eng = engine or _engine()
    async with eng.connect() as conn:
        if owner is None:
            rows = (await conn.execute(_LIST_ALL, {"brand": brand_id})).mappings().all()
        else:
            rows = (await conn.execute(_LIST_OWNED, {"brand": brand_id, "owner": owner})).mappings().all()
    return [_decode(r) for r in rows]


async def count_active_owned(brand_id: str, owner: str, *, engine: Any | None = None) -> int:
    eng = engine or _engine()
    async with eng.connect() as conn:
        row = (await conn.execute(_COUNT_OWNED, {"brand": brand_id, "owner": owner})).mappings().first()
    return int(row["n"]) if row else 0


async def delete_job(job_id: str, *, owner: str | None = None, engine: Any | None = None) -> bool:
    """Delete a job. If `owner` is given (self-scoped cancel), only deletes a job with that owner."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        if owner is None:
            await conn.execute(_DELETE_JOB, {"id": job_id})
            return True
        row = (await conn.execute(_DELETE_JOB_SCOPED, {"id": job_id, "owner": owner})).mappings().first()
    return row is not None


async def update_job(job_id: str, patch: dict, *, now: datetime, engine: Any | None = None) -> dict | None:
    """Patch a job. Supports enabled, payload, pacing, and rescheduling (schedule_kind+schedule)."""
    eng = engine or _engine()
    sets: list[str] = ["updated_at=now()"]
    params: dict[str, Any] = {"id": job_id}
    if "enabled" in patch:
        sets.append("enabled=:enabled")
        params["enabled"] = bool(patch["enabled"])
        if patch["enabled"]:  # re-enabling clears the failure state
            sets.append("fail_count=0")
            sets.append("disabled_reason=NULL")
    if "payload" in patch:
        sets.append("payload=cast(:payload as jsonb)")
        params["payload"] = json.dumps(patch["payload"])
    if "pacing" in patch:
        sets.append("pacing=cast(:pacing as jsonb)")
        params["pacing"] = json.dumps(patch["pacing"])
    if "schedule" in patch and "schedule_kind" in patch:
        sched.validate(patch["schedule"], patch["schedule_kind"])
        sets.append("schedule_kind=:schedule_kind")
        sets.append("schedule=cast(:schedule as jsonb)")
        sets.append("next_run_at=:next")
        params["schedule_kind"] = patch["schedule_kind"]
        params["schedule"] = json.dumps(patch["schedule"])
        params["next"] = sched.compute_first_run(patch["schedule"], patch["schedule_kind"], now=now)
    stmt = text(f"UPDATE scheduled_jobs SET {', '.join(sets)} WHERE id=:id")
    async with eng.begin() as conn:
        await conn.execute(stmt, params)
    return await get_job(job_id, engine=engine)


async def open_run(job_id: str, brand_id: str, *, engine: Any | None = None) -> str:
    """Open a `scheduled_runs` row out-of-band (used by force-run). Returns the run_id."""
    eng = engine or _engine()
    run_id = _uuid.uuid4().hex
    async with eng.begin() as conn:
        await conn.execute(_INSERT_RUN, {"id": run_id, "job_id": job_id, "brand_id": brand_id})
    return run_id


async def set_next_run(job_id: str, next_run_at: datetime, *, engine: Any | None = None) -> None:
    """Used by `next_check` self-pacing to move a job's next fire."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_SET_NEXT, {"id": job_id, "next": next_run_at})
