"""Influencer content-plan — DB-backed store (core.influencer_post_plan).

INFLUENCER-COCKPIT lane (2026-06-03). The operator-facing surface for
the AI influencer pipeline is now the Mesh Pilot cockpit
(/dashboard/influencer -> /v1/influencer), not a Google Sheet. This
module is the *agent-side* reader/writer of the same brand-scoped table
the cockpit serves, so discovery, the operator UI, and the generation
worker all share one source of truth.

  Discovery  -> INSERT idea rows (status='idea')
  Operator   -> approves in the cockpit (status='approved')
  This module -> next_approved() leases the top approved row, the
                 worker generates against the persona's locked
                 reference sheets, then write_back() stamps
                 status/asset_url/post_url.

Table: core.influencer_post_plan (glitch_brain). FK to
core.influencer_personas(brand_id, persona_id) / core.brands.
Migration: migrations/2026-06-03-influencer-content-plan.sql

Env: POSTGRES_BRAIN_URL — the v1 monorepo hub DSN. Not configured in prod or local env, so this
module cannot run as-is; `shared_context.py`, which shared that DSN, was removed as dead on
2026-09-02.

⚠️ KEEP. This is NOT dead code awaiting cleanup — the operator retained it deliberately
(2026-09-02) as planned Mesh Pilot work. Do not delete it on the grounds that it cannot run; the
missing DSN is the blocker, not the module.

The previous Google-Sheet implementation is archived at
archive/influencer-sheet-content-plan-2026-06-03/content_plan_sheet.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import asyncpg

_TABLE = "core.influencer_post_plan"
# Columns the worker is allowed to write back (never brand_id/persona_id/id).
_WRITABLE = {
    "pillar", "platform", "format", "hook", "caption", "status",
    "scheduled_for", "asset_url", "post_url", "platform_post_id", "notes",
}

_pool: asyncpg.Pool | None = None


async def _ensure_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        url = os.environ.get("POSTGRES_BRAIN_URL") or os.environ.get("HUB_DB_URL")
        if not url:
            raise RuntimeError(
                "POSTGRES_BRAIN_URL not configured — the influencer content "
                "plan now lives in core.influencer_post_plan (glitch_brain)."
            )
        _pool = await asyncpg.create_pool(url, min_size=1, max_size=3)
    return _pool


@dataclass(slots=True)
class PlanRow:
    id: int
    brand_id: str
    persona_id: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def persona(self) -> str:  # back-compat with the old sheet API
        return self.persona_id

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def _to_row(r: asyncpg.Record) -> PlanRow:
    d = dict(r)
    return PlanRow(
        id=int(d["id"]), brand_id=d["brand_id"], persona_id=d["persona_id"],
        status=(d.get("status") or "").strip().lower(), data=d,
    )


async def fetch_rows(
    brand_id: str, *, status: str | None = None, persona: str | None = None,
) -> list[PlanRow]:
    """Read plan rows for a brand (optionally filtered by status / persona)."""
    pool = await _ensure_pool()
    clauses = ["brand_id = $1"]
    params: list[Any] = [brand_id]
    if status:
        params.append(status)
        clauses.append(f"status = ${len(params)}")
    if persona:
        params.append(persona)
        clauses.append(f"persona_id = ${len(params)}")
    where = " AND ".join(clauses)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT * FROM {_TABLE} WHERE {where}
                ORDER BY COALESCE(scheduled_for, created_at), id""",
            *params,
        )
    return [_to_row(r) for r in rows]


async def next_approved(brand_id: str, *, persona: str | None = None) -> PlanRow | None:
    """The next row the worker should act on (status=approved, top-down).

    Atomically flips it to 'generating' so concurrent workers don't pick
    the same row (the cockpit equivalent of leasing a sheet row).
    """
    pool = await _ensure_pool()
    clauses = ["brand_id = $1", "status = 'approved'"]
    params: list[Any] = [brand_id]
    if persona:
        params.append(persona)
        clauses.append(f"persona_id = ${len(params)}")
    where = " AND ".join(clauses)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""UPDATE {_TABLE} SET status = 'generating'
                WHERE id = (
                    SELECT id FROM {_TABLE}
                    WHERE {where}
                    ORDER BY COALESCE(scheduled_for, created_at), id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *""",
            *params,
        )
    return _to_row(row) if row else None


async def write_back(plan_id: int, updates: dict[str, Any]) -> None:
    """Patch writable columns on a plan row (status, asset_url, post_url…)."""
    fields = {k: v for k, v in updates.items() if k in _WRITABLE}
    if not fields:
        return
    pool = await _ensure_pool()
    cols = list(fields)
    sets = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cols))
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE {_TABLE} SET {sets} WHERE id = $1",
            plan_id, *[fields[c] for c in cols],
        )


async def add_idea(
    brand_id: str, persona_id: str, *,
    discovery_source: str = "discovery", score: float | None = None, **fields: Any,
) -> int:
    """Discovery entry point — insert an idea row, return its id."""
    allowed = {k: v for k, v in fields.items() if k in _WRITABLE and k != "status"}
    if score is not None:
        allowed["score"] = score
    cols = ["brand_id", "persona_id", "discovery_source", "created_by", "status", *allowed]
    vals = [brand_id, persona_id, discovery_source, "discovery", "idea", *allowed.values()]
    placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"INSERT INTO {_TABLE} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            *vals,
        )
    return int(row["id"])


async def auto_approve(
    brand_id: str, persona_ids: list[str], *, keep: int = 2, max_age_days: int = 5,
    formats: list[str] | None = None,
) -> list[int]:
    """Hands-off approval: promote the freshest idea rows to 'approved' for
    the given personas, topping each persona's approved buffer up to `keep`.

    This replaces the human approval gate when INFLUENCER_AUTO_APPROVE is on.
    Bounded (never leaves more than `keep` approved per call cohort) and
    freshness-filtered (ignores ideas older than `max_age_days`) so a large
    idea backlog can neither flood the funnel nor resurface stale content.
    Stamps approved_by='auto' / approved_at for auditability. The caller is
    responsible for passing only personas that can actually post (a connected
    Meta account) so auto-approved rows do not fail at the posting stage.
    `formats`, when given, restricts promotion to those formats (e.g.
    ['carousel', 'still']) — used to skip formats whose generation engine
    is currently unavailable (e.g. video/reels when HeyGen has no credit).
    """
    if not persona_ids or keep <= 0:
        return []
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchval(
            f"""SELECT count(*) FROM {_TABLE}
                WHERE brand_id = $1 AND status = 'approved'
                  AND persona_id = ANY($2::text[])""",
            brand_id, persona_ids,
        )
        needed = keep - int(current or 0)
        if needed <= 0:
            return []
        rows = await conn.fetch(
            f"""UPDATE {_TABLE} SET status = 'approved',
                       approved_by = 'auto', approved_at = NOW()
                WHERE id IN (
                    SELECT id FROM {_TABLE}
                    WHERE brand_id = $1 AND status = 'idea'
                      AND persona_id = ANY($2::text[])
                      AND created_at >= NOW() - make_interval(days => $3)
                      AND (cardinality($5::text[]) = 0
                           OR COALESCE(format, '') = ANY($5::text[]))
                    ORDER BY COALESCE(scheduled_for, created_at) DESC, id DESC
                    FOR UPDATE SKIP LOCKED
                    LIMIT $4
                )
                RETURNING id""",
            brand_id, persona_ids, max_age_days, needed, formats or [],
        )
    return [int(r["id"]) for r in rows]
