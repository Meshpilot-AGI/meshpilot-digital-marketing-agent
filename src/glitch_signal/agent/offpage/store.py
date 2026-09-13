"""OFF-PAGE store — the spine's rows, and nothing lever-specific.

`offpage_candidate` is what we could say and where; `offpage_outcome` is what happened after we
said it. Every lever (syndicate, reply, haro) writes the same rows, which is what gives the operator
one approval UX and one digest. Design: docs/plans/2026-09-12-offpage-seo.md § 3.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


_INSERT = text(
    "INSERT INTO offpage_candidate (brand_id, lever, surface_kind, surface, target_url, source_ref, "
    "  score, draft, draft_meta, status) "
    "VALUES (:b, :lever, :kind, :surface, :target, :source, :score, :draft, CAST(:meta AS jsonb), :status) "
    "RETURNING id"
)

_SET_STATUS = text(
    "UPDATE offpage_candidate SET status = :status, decided_at = CASE WHEN :decided THEN now() "
    "ELSE decided_at END WHERE id = :id"
)

_OUTCOME = text(
    "INSERT INTO offpage_outcome (candidate_id, brand_id, lever, posted_url, error, metrics) "
    "VALUES (:id, :b, :lever, :url, :err, CAST(:metrics AS jsonb))"
)

_BY_SOURCE = text(
    "SELECT source_ref, surface_kind, status, created_at FROM offpage_candidate "
    "WHERE brand_id = :b AND lever = :lever"
)


async def add_candidate(brand_id: str, *, lever: str, surface_kind: str, surface: str, draft: str,
                        target_url: str | None = None, source_ref: str | None = None,
                        score: float | None = None, meta: dict | None = None,
                        status: str = "drafted", engine: Any = None) -> str:
    async with _engine_or(engine).begin() as conn:
        row = await conn.execute(_INSERT, {
            "b": brand_id, "lever": lever, "kind": surface_kind, "surface": surface,
            "target": target_url, "source": source_ref, "score": score, "draft": draft,
            "meta": json.dumps(meta or {}), "status": status})
        return str(row.scalar_one())


async def set_status(candidate_id: str, status: str, *, decided: bool = False,
                     engine: Any = None) -> None:
    async with _engine_or(engine).begin() as conn:
        await conn.execute(_SET_STATUS, {"id": candidate_id, "status": status, "decided": decided})


async def record_outcome(candidate_id: str, brand_id: str, lever: str, *, posted_url: str | None,
                         error: str | None = None, metrics: dict | None = None,
                         engine: Any = None) -> None:
    async with _engine_or(engine).begin() as conn:
        await conn.execute(_OUTCOME, {"id": candidate_id, "b": brand_id, "lever": lever,
                                      "url": posted_url, "err": error,
                                      "metrics": json.dumps(metrics or {})})


async def candidates_by_source(brand_id: str, lever: str, *, engine: Any = None) -> list[dict]:
    """Every candidate of a lever, as dicts — the finder's "what have we already done" view."""
    async with _engine_or(engine).connect() as conn:
        rows = (await conn.execute(_BY_SOURCE, {"b": brand_id, "lever": lever})).mappings().all()
    return [dict(r) for r in rows]
