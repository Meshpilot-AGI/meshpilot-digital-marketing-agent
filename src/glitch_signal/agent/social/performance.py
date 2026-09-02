"""Aggregate measured outcomes per matrix cell — the evidence the curator is allowed to reason from.

Joins `social_post_metric` (measured outcomes) against `social_campaign.choices` (what the agent
decided) to produce per-(asset_kind, pillar, platform) means.

- Comparisons use a single age bucket (24h default) — comparing a 7d read against a 1h read measures
  how long each post had been up, not the content.
- Meta exposes no impressions/reach for these Page posts, so engagement is an absolute count,
  confounded by posting time and follower growth — hence the ranking threshold below.
- Platform is part of the cell key: Facebook and Instagram have different audiences and engagement
  scales, so pooling them would let platform mix decide the winner instead of the content choice.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.agent.social.matrix import MIN_SAMPLES_TO_RANK
from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

DEFAULT_BUCKET = "24h"

# Video views excluded: they only accrue on video posts, so including them would favor video cells
# for reasons unrelated to the content idea.
_ENGAGEMENT = ("coalesce(m.likes,0) + coalesce(m.comments,0) + coalesce(m.shares,0) "
               "+ coalesce(m.clicks,0)")

# All-NULL means a failed/partial collector read, not a genuine zero — must not drag the mean down.
_UNMEASURED = ("m.likes IS NULL AND m.comments IS NULL AND m.shares IS NULL AND m.clicks IS NULL")


class PerformanceQueryError(RuntimeError):
    """`by_cell` could not complete its query — distinct from a DB/SQL failure that should never
    look like `summarise([])`'s normal "no evidence yet" result."""


async def by_cell(brand_id: str, *, bucket: str = DEFAULT_BUCKET,
                  engine: Any = None) -> list[dict]:
    """Per (asset_kind, pillar, platform): sample size and mean engagement at one age bucket.

    Raises `PerformanceQueryError` on failure rather than returning `[]`."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            rows = (await conn.execute(
                text(f"SELECT c.choices->>'asset_kind' AS asset_kind, "
                     f"       c.choices->>'pillar'     AS pillar, "
                     f"       m.platform                AS platform, "
                     f"       count(*)                 AS n, "
                     f"       avg({_ENGAGEMENT})::float AS mean_engagement, "
                     f"       sum({_ENGAGEMENT})        AS total_engagement "
                     f"FROM social_post_metric m "
                     f"JOIN social_post p     ON p.id = m.post_id "
                     f"JOIN social_campaign c ON c.id = p.campaign_id "
                     f"WHERE c.brand_id = :brand AND m.age_bucket = :bucket "
                     f"  AND c.choices->>'asset_kind' IS NOT NULL "
                     f"  AND c.choices->>'pillar' IS NOT NULL "
                     f"  AND NOT ({_UNMEASURED}) "
                     f"GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"),
                {"brand": brand_id, "bucket": bucket})).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 — re-raised as a typed, distinguishable failure
        log.warning("social.performance_query_failed", brand_id=brand_id, error=str(exc)[:200])
        raise PerformanceQueryError(str(exc)) from exc


def summarise(cells: list[dict]) -> dict[str, Any]:
    """Turn per-cell rows into a verdict about what, if anything, may be concluded.

Cells below `MIN_SAMPLES_TO_RANK` are reported but not ranked — ordering a mean of one or two
    posts is superstition.

    Ranking never crosses platforms: absolute engagement on Facebook and Instagram is not
    comparable, and the matrix controls asset_kind and pillar, not platform. So cells are ranked
    within a platform, and `can_conclude` needs two rankable cells on the SAME one.
    """
    rankable = [c for c in cells if (c.get("n") or 0) >= MIN_SAMPLES_TO_RANK]

    by_platform: dict[Any, list[dict]] = {}
    for c in rankable:
        by_platform.setdefault(c.get("platform"), []).append(c)

    ranked: list[dict] = []
    can_conclude = False
    for platform in sorted(by_platform, key=lambda p: (p is None, str(p))):
        group = by_platform[platform]
        group.sort(key=lambda c: (c.get("mean_engagement") or 0.0), reverse=True)
        if len(group) >= 2:
            can_conclude = True
        ranked.extend(group)                    # still surfaced, just never compared cross-platform

    return {
        "cells_observed": len(cells),
        "cells_rankable": len(rankable),
        "min_samples_to_rank": MIN_SAMPLES_TO_RANK,
        "can_conclude": can_conclude,
        "ranked": ranked,
        "under_sampled": sorted(
            (c for c in cells if (c.get("n") or 0) < MIN_SAMPLES_TO_RANK),
            key=lambda c: (c.get("n") or 0), reverse=True),
    }


def evidence_block(summary: dict[str, Any]) -> str:
    """Render the evidence for the curator, or an explicit "not enough evidence" line — an empty
    section reads to a model as license to reason from its priors instead."""
    if not summary.get("can_conclude"):
        return (f"NOT ENOUGH EVIDENCE. {summary.get('cells_rankable', 0)} of "
                f"{summary.get('cells_observed', 0)} observed cells have reached "
                f"{summary.get('min_samples_to_rank')} posts. Draw NO conclusions about what "
                f"performs better.")
    lines = ["MEASURED PERFORMANCE (mean engagement at 24h, absolute — reach is not available):"]
    for c in summary["ranked"]:
        lines.append(f"- {c['asset_kind']} × {c['pillar']} × {c.get('platform')}: "
                     f"{c['mean_engagement']:.2f} mean over n={c['n']}")
    return "\n".join(lines)
