"""SURFACES (TARGET-2) — deciding *where* to speak, from evidence rather than assumption.

The content matrix answers "what format next". Nothing answered "in which room", so the agent
broadcast to a fixed platform list. This ranks the rooms sensing has found.

**The scoring claim, stated plainly so it can be argued with:**

    fit = relevance_density × (0.5 + 0.5 × reach_norm)

Relevance dominates and reach only modulates it. That is deliberate, and it is the whole opinion of
this module: **a small room full of your audience beats a large room that merely contains them.**
Concretely — r/Forex has 547,438 subscribers and r/PropFirmTester 28,258, roughly 19x. If the brand's
queries keep surfacing threads in the smaller room, it should win, because reach you cannot address
is not reach. A purely reach-ranked list would send every brand to the biggest generic room, which is
exactly the broadcast behaviour this replaces.

`reach_norm` is logarithmic: the difference between 1k and 10k subscribers matters far more than
between 500k and 5M, because participation is bounded by attention in a thread, not by the room's
total size.

**What this module refuses to do.** Until measured engagement exists for a surface, its score is
marked `provisional` — a prior, not a finding. This mirrors `MIN_SAMPLES_TO_RANK` in the matrix and
the curator that declines to conclude below threshold. The agent has never posted to Reddit, so at
the time of writing *every* surface is provisional, and callers must present them as candidates
rather than as evidence.

Nothing here names a subreddit, platform or industry.
"""
from __future__ import annotations

import json
import math
from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.agent.social.matrix import MIN_SAMPLES_TO_RANK

log = structlog.get_logger(__name__)

# Reach is normalised against this ceiling on a log scale: 1e6 members ≈ 1.0. Above it the extra
# size buys nothing a participant can use.
_REACH_CEILING = 1_000_000

# `MIN_SAMPLES_TO_RANK` (imported above) is reused deliberately: below that many measured outcomes a
# surface's score stays `provisional`. One threshold for "we know", not two competing ones.

_UPSERT = text(
    "INSERT INTO surface (brand_id, kind, handle, display_name, reach) "
    "VALUES (:brand_id, :kind, :handle, :display_name, :reach) "
    "ON CONFLICT (brand_id, kind, handle) DO UPDATE SET "
    "  display_name = coalesce(EXCLUDED.display_name, surface.display_name), "
    "  reach = coalesce(EXCLUDED.reach, surface.reach), "
    "  updated_at = now()"
)

# Relevance density comes from what sensing actually observed, not from anything asserted.
_REFRESH_SIGNALS = text(
    "UPDATE surface s SET signal_count = c.n, last_signal_at = c.latest, updated_at = now() "
    "FROM (SELECT surface AS handle, count(*) AS n, max(observed_at) AS latest "
    "      FROM signal_item WHERE brand_id = :brand_id AND surface IS NOT NULL "
    "      GROUP BY surface) c "
    "WHERE s.brand_id = :brand_id AND s.handle = c.handle"
)

_SELECT_FOR_SCORING = text(
    "SELECT id, handle, reach, signal_count, self_promo_allowed, status FROM surface "
    "WHERE brand_id = :brand_id"
)

_WRITE_SCORE = text(
    "UPDATE surface SET fit_score = :fit, score_components = CAST(:components AS jsonb), "
    "  scored_at = now(), provisional = :provisional, updated_at = now() WHERE id = :id"
)

_TOP = text(
    "SELECT kind, handle, display_name, status, reach, signal_count, fit_score, "
    "       score_components, provisional, self_promo_allowed "
    "FROM surface WHERE brand_id = :brand_id "
    "  AND (CAST(:kind AS text) IS NULL OR kind = :kind) "
    "  AND (NOT :postable_only OR (status = 'active' AND self_promo_allowed IS TRUE)) "
    "ORDER BY fit_score DESC NULLS LAST, signal_count DESC LIMIT :limit"
)

_SET_RULES = text(
    "UPDATE surface SET rules = CAST(:rules AS jsonb), rules_fetched_at = now(), "
    "  self_promo_allowed = :allowed, status = :status, updated_at = now() "
    "WHERE brand_id = :brand_id AND kind = :kind AND handle = :handle"
)


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


def reach_norm(reach: int | None) -> float:
    """Log-normalised reach in 0..1. None/0 → 0.0 (unknown size earns nothing, it is not assumed)."""
    if not reach or reach <= 0:
        return 0.0
    return min(1.0, math.log10(reach) / math.log10(_REACH_CEILING))


def fit(signal_count: int, total_signals: int, reach: int | None) -> tuple[float, dict]:
    """The score, and the components that produced it.

    Components are returned so a ranking can always be explained — "why is this room above that one"
    should never require re-deriving the number.
    """
    density = (signal_count / total_signals) if total_signals > 0 else 0.0
    rn = reach_norm(reach)
    score = density * (0.5 + 0.5 * rn)
    return round(score, 6), {
        "relevance_density": round(density, 6),
        "reach_norm": round(rn, 6),
        "signal_count": signal_count,
        "total_signals": total_signals,
        "reach": reach,
        "formula": "density * (0.5 + 0.5 * reach_norm)",
    }


async def upsert_discovered(brand_id: str, kind: str, rooms: list[dict], *, engine: Any = None) -> int:
    """Record rooms that sensing found. Idempotent — re-discovery refreshes, never duplicates."""
    rows = [r for r in (rooms or []) if (r.get("name") or r.get("handle"))]
    if not rows:
        return 0
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            for r in rows:
                await conn.execute(_UPSERT, {
                    "brand_id": brand_id, "kind": kind,
                    "handle": str(r.get("name") or r.get("handle")),
                    "display_name": r.get("title") or r.get("display_name"),
                    "reach": r.get("subscribers") or r.get("reach") or r.get("followers"),
                })
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — discovery must not fail because bookkeeping did
        log.warning("surfaces.upsert_failed", error=str(exc)[:200])
        return 0


async def rescore(brand_id: str, *, measured: dict[str, int] | None = None,
                  engine: Any = None) -> list[dict]:
    """Recompute every surface's fit from stored evidence. No network — re-scoring is free.

    `measured` maps handle -> number of measured outcomes there; a surface at or above
    `MIN_SAMPLES_TO_RANK` stops being provisional. Absent, everything stays provisional, which is
    the honest state today: nothing has been posted to these rooms yet.
    """
    measured = measured or {}
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            await conn.execute(_REFRESH_SIGNALS, {"brand_id": brand_id})
            rows = [dict(r) for r in
                    (await conn.execute(_SELECT_FOR_SCORING, {"brand_id": brand_id})).mappings().all()]
            total = sum(int(r.get("signal_count") or 0) for r in rows)
            out = []
            for r in rows:
                score, comp = fit(int(r.get("signal_count") or 0), total, r.get("reach"))
                n = int(measured.get(str(r.get("handle")), 0))
                comp["measured_outcomes"] = n
                prov = n < MIN_SAMPLES_TO_RANK
                await conn.execute(_WRITE_SCORE, {
                    "id": r["id"], "fit": score, "components": json.dumps(comp), "provisional": prov,
                })
                out.append({"handle": r.get("handle"), "fit_score": score, "provisional": prov})
            return sorted(out, key=lambda x: x["fit_score"], reverse=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("surfaces.rescore_failed", error=str(exc)[:200])
        return []


async def top(brand_id: str, *, kind: str | None = None, limit: int = 10,
              postable_only: bool = False, engine: Any = None) -> list[dict]:
    """The ranked answer to "where next".

    `postable_only` narrows to rooms we are actually allowed to post in — `status='active'` AND
    `self_promo_allowed IS TRUE`. NULL is excluded deliberately: unknown is not permission.
    """
    try:
        eng = _engine_or(engine)
        async with eng.connect() as conn:
            res = await conn.execute(_TOP, {"brand_id": brand_id, "kind": kind,
                                            "postable_only": postable_only,
                                            "limit": max(1, min(limit, 100))})
            return [dict(r) for r in res.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("surfaces.top_failed", error=str(exc)[:200])
        return []


async def record_rules(brand_id: str, kind: str, handle: str, rules: Any, *,
                       self_promo_allowed: bool | None = None, engine: Any = None) -> bool:
    """Store a room's rules, captured BEFORE we ever act in it.

    A room that forbids self-promotion becomes `read_only` — still worth listening to, never posted
    into. That is a decision made from the room's own stated rules rather than from our appetite.
    """
    status = "read_only" if self_promo_allowed is False else "candidate"
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            await conn.execute(_SET_RULES, {
                "brand_id": brand_id, "kind": kind, "handle": handle,
                "rules": json.dumps(rules if rules is not None else {}),
                "allowed": self_promo_allowed, "status": status,
            })
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("surfaces.record_rules_failed", error=str(exc)[:200])
        return False
