"""Aggregate measured outcomes per matrix cell — the evidence the curator is allowed to reason from.

`social_post_metric` holds one row per post per age bucket; `social_campaign.choices` holds what the
agent decided. Joining them is what turns "this post got 4 comments" into "comparison posts in the
rule-mechanics pillar average X" — the only form in which an outcome can support a lesson.

Two constraints shape everything here.

SAME AGE. Comparisons use ONE bucket (24h by default). A post read at 7d against another read at 1h
is not a comparison, it is a measurement of how long each had been up.

NO NORMALISATION IS POSSIBLE. Meta does not expose impressions or reach for these Page posts (see
`platforms/insights.py`), so engagement cannot be divided by the audience that saw it. Everything
here is therefore an ABSOLUTE count, which is confounded by posting time and by follower growth over
the period. That is a real limitation, stated rather than hidden, and it is why the ranking
threshold exists.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.agent.social.matrix import MIN_SAMPLES_TO_RANK
from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

DEFAULT_BUCKET = "24h"

# Engagement is the sum of the deliberate actions we can actually read. Video views are excluded:
# they accrue on video posts only, so including them would make a video cell look better than an
# image cell for reasons that have nothing to do with the idea.
_ENGAGEMENT = ("coalesce(m.likes,0) + coalesce(m.comments,0) + coalesce(m.shares,0) "
               "+ coalesce(m.clicks,0)")


async def by_cell(brand_id: str, *, bucket: str = DEFAULT_BUCKET,
                  engine: Any = None) -> list[dict]:
    """Per (asset_kind, pillar): sample size and mean engagement at one age bucket."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            rows = (await conn.execute(
                text(f"SELECT c.choices->>'asset_kind' AS asset_kind, "
                     f"       c.choices->>'pillar'     AS pillar, "
                     f"       count(*)                 AS n, "
                     f"       avg({_ENGAGEMENT})::float AS mean_engagement, "
                     f"       sum({_ENGAGEMENT})        AS total_engagement "
                     f"FROM social_post_metric m "
                     f"JOIN social_post p     ON p.id = m.post_id "
                     f"JOIN social_campaign c ON c.id = p.campaign_id "
                     f"WHERE c.brand_id = :brand AND m.age_bucket = :bucket "
                     f"  AND c.choices->>'asset_kind' IS NOT NULL "
                     f"GROUP BY 1, 2 ORDER BY 1, 2"),
                {"brand": brand_id, "bucket": bucket})).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 — no evidence is a valid state, not a failure
        log.warning("social.performance_query_failed", brand_id=brand_id, error=str(exc)[:200])
        return []


def summarise(cells: list[dict]) -> dict[str, Any]:
    """Turn per-cell rows into a verdict about what, if anything, may be concluded.

    `rankable` is the whole point. Below `MIN_SAMPLES_TO_RANK` a cell's mean is one or two posts and
    ordering those is superstition — so cells under the threshold are reported but explicitly not
    ranked, and `can_conclude` stays False until at least two cells clear it (one ranked cell has
    nothing to be better THAN).
    """
    ranked = [c for c in cells if (c.get("n") or 0) >= MIN_SAMPLES_TO_RANK]
    ranked.sort(key=lambda c: (c.get("mean_engagement") or 0.0), reverse=True)
    return {
        "cells_observed": len(cells),
        "cells_rankable": len(ranked),
        "min_samples_to_rank": MIN_SAMPLES_TO_RANK,
        "can_conclude": len(ranked) >= 2,
        "ranked": ranked,
        "under_sampled": sorted(
            (c for c in cells if (c.get("n") or 0) < MIN_SAMPLES_TO_RANK),
            key=lambda c: (c.get("n") or 0), reverse=True),
    }


def evidence_block(summary: dict[str, Any]) -> str:
    """Render the evidence for the curator, or a plain statement that there is none.

    Returning an explicit "not enough evidence" line rather than an empty section matters: an empty
    evidence block reads to a model as an invitation to reason from its priors, which is exactly how
    an unfounded lesson gets written down as durable.
    """
    if not summary.get("can_conclude"):
        return (f"NOT ENOUGH EVIDENCE. {summary.get('cells_rankable', 0)} of "
                f"{summary.get('cells_observed', 0)} observed cells have reached "
                f"{summary.get('min_samples_to_rank')} posts. Draw NO conclusions about what "
                f"performs better.")
    lines = ["MEASURED PERFORMANCE (mean engagement at 24h, absolute — reach is not available):"]
    for c in summary["ranked"]:
        lines.append(f"- {c['asset_kind']} × {c['pillar']}: "
                     f"{c['mean_engagement']:.2f} mean over n={c['n']}")
    return "\n".join(lines)
