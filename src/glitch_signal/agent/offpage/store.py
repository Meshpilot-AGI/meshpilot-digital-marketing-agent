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


# ----------------------------------------------------------------------------- the reply ladder's views

_BY_STATUS = text(
    "SELECT id, brand_id, lever, surface_kind, surface, target_url, source_ref, score, draft, "
    "       draft_meta, status, discord_msg_id, offered_at, decided_at, expires_at, created_at "
    "FROM offpage_candidate WHERE brand_id = :b AND lever = :lever AND status = ANY(:statuses) "
    "ORDER BY created_at"
)

_RECENT = text(
    "SELECT id, surface, target_url, status, created_at, decided_at FROM offpage_candidate "
    "WHERE brand_id = :b AND lever = :lever AND created_at >= now() - CAST(:hours || ' hours' AS interval)"
)

_OFFER = text(
    "UPDATE offpage_candidate SET status = 'offered', discord_msg_id = :msg, offered_at = now(), "
    "expires_at = now() + CAST(:hours || ' hours' AS interval) WHERE id = :id"
)

_EXPIRE = text(
    "UPDATE offpage_candidate SET status = 'expired' WHERE brand_id = :b AND lever = :lever "
    "AND status = 'offered' AND expires_at < now() RETURNING id"
)

_STANDING = text(
    "INSERT INTO offpage_standing (brand_id, surface_kind, account_age_days, comment_karma, link_karma, "
    "  approvals_30d, rejections_30d, posted_by_operator_30d) "
    "VALUES (:b, :kind, :age, :ck, :lk, :ap, :rj, :po)"
)

_LATEST_STANDING = text(
    "SELECT * FROM offpage_standing WHERE brand_id = :b AND surface_kind = :kind "
    "ORDER BY checked_at DESC LIMIT 1"
)

_HISTORY = text(
    "SELECT status, decided_at, created_at FROM offpage_candidate WHERE brand_id = :b AND lever = :lever "
    "AND status IN ('posted_by_agent', 'rejected', 'removed') ORDER BY created_at DESC LIMIT 60"
)


async def by_status(brand_id: str, lever: str, statuses: list[str], *, engine: Any = None) -> list[dict]:
    async with _engine_or(engine).connect() as conn:
        rows = (await conn.execute(_BY_STATUS, {"b": brand_id, "lever": lever,
                                                "statuses": statuses})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("draft_meta"), str):
            d["draft_meta"] = json.loads(d["draft_meta"])
        out.append(d)
    return out


async def recent(brand_id: str, lever: str, *, hours: int, engine: Any = None) -> list[dict]:
    """Candidates created in the last `hours` — the cadence caps read this."""
    async with _engine_or(engine).connect() as conn:
        rows = (await conn.execute(_RECENT, {"b": brand_id, "lever": lever,
                                             "hours": str(int(hours))})).mappings().all()
    return [dict(r) for r in rows]


async def mark_offered(candidate_id: str, discord_msg_id: str, *, ttl_hours: int,
                       engine: Any = None) -> None:
    async with _engine_or(engine).begin() as conn:
        await conn.execute(_OFFER, {"id": candidate_id, "msg": discord_msg_id,
                                    "hours": str(int(ttl_hours))})


async def expire_stale(brand_id: str, lever: str, *, engine: Any = None) -> list[str]:
    async with _engine_or(engine).begin() as conn:
        rows = (await conn.execute(_EXPIRE, {"b": brand_id, "lever": lever})).scalars().all()
    return [str(r) for r in rows]


async def record_standing(brand_id: str, surface_kind: str, *, account_age_days: int | None,
                          comment_karma: int | None, link_karma: int | None, approvals_30d: int,
                          rejections_30d: int, posted_by_operator_30d: int,
                          engine: Any = None) -> None:
    async with _engine_or(engine).begin() as conn:
        await conn.execute(_STANDING, {"b": brand_id, "kind": surface_kind, "age": account_age_days,
                                       "ck": comment_karma, "lk": link_karma, "ap": approvals_30d,
                                       "rj": rejections_30d, "po": posted_by_operator_30d})


async def latest_standing(brand_id: str, surface_kind: str, *, engine: Any = None) -> dict | None:
    async with _engine_or(engine).connect() as conn:
        row = (await conn.execute(_LATEST_STANDING, {"b": brand_id, "kind": surface_kind})).mappings().first()
    return dict(row) if row else None


async def agent_post_history(brand_id: str, lever: str, *, engine: Any = None) -> list[dict]:
    """Newest-first statuses of the agent's own posts and every rejection/removal — R2's evidence."""
    async with _engine_or(engine).connect() as conn:
        rows = (await conn.execute(_HISTORY, {"b": brand_id, "lever": lever})).mappings().all()
    return [dict(r) for r in rows]
