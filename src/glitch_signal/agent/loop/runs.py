"""Shared run store for the backgrounded agent-loop endpoint (AGENT-LOOP).

The run endpoint returns a `run_id` immediately and executes the loop under
`asyncio.create_task`. FastAPI Cloud runs multiple workers, so run state must live somewhere
every worker can read — an in-process dict is not pollable (POST and GET can hit different
workers). This persists run state to Postgres (`agent_runs`) and reads it back by id.

The SQLAlchemy `engine` is injectable so this unit-tests without a real DB.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from glitch_signal.db.session import _engine

_CREATE = text(
    "INSERT INTO agent_runs (run_id, brand_id, goal, status) "
    "VALUES (:run_id, :brand_id, :goal, 'running') "
    "ON CONFLICT (run_id) DO NOTHING"
)
_FINISH = text(
    "UPDATE agent_runs SET status=:status, steps=:steps, final=:final, "
    "transcript=cast(:transcript as jsonb), deliberation=cast(:deliberation as jsonb), "
    "error=:error, updated_at=now() WHERE run_id=:run_id"
)
_GET = text(
    "SELECT run_id, brand_id, status, steps, final, transcript, deliberation, error "
    "FROM agent_runs WHERE run_id=:run_id"
)


def _deliberation(result: dict) -> str:
    """Extract the reckoning + conscience passes from a run result → a JSON object for the column."""
    return json.dumps({k: result[k] for k in ("reckoning", "conscience") if result.get(k)})


async def create_run(run_id: str, brand_id: str, goal: str, *, engine: Any | None = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_CREATE, {"run_id": run_id, "brand_id": brand_id, "goal": goal})


async def finish_run(run_id: str, result: dict, *, engine: Any | None = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_FINISH, {
            "run_id": run_id,
            "status": "done",
            "steps": result.get("steps"),
            "final": result.get("final"),
            "transcript": json.dumps(result.get("transcript", [])),
            "deliberation": _deliberation(result),
            "error": None,
        })


async def fail_run(run_id: str, error: str, *, engine: Any | None = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_FINISH, {
            "run_id": run_id,
            "status": "error",
            "steps": None,
            "final": None,
            "transcript": json.dumps([]),
            "deliberation": "{}",
            "error": error[:2000],
        })


async def get_run(run_id: str, *, engine: Any | None = None) -> dict | None:
    eng = engine or _engine()
    async with eng.connect() as conn:
        row = (await conn.execute(_GET, {"run_id": run_id})).mappings().first()
    if row is None:
        return None
    d = dict(row)
    tr = d.get("transcript")
    if isinstance(tr, str):
        d["transcript"] = json.loads(tr)
    delib = d.pop("deliberation", None)
    if isinstance(delib, str):
        delib = json.loads(delib or "{}")
    if isinstance(delib, dict):
        d.update(delib)   # expose reckoning/conscience at the top level (matches the run-result shape)
    return d
