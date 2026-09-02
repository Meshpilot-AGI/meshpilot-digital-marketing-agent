"""The content matrix — deliberate variation, so outcomes are attributable.

Two problems this solves, and they are the same problem seen from both ends.

MEASUREMENT: `social_post_metric` records what happened, but a number is only useful if you can say
what produced it. Recording the CHOICES (asset kind × pillar) gives the outcome analysis something
to group by; without it "comparison posts land well" is an unfalsifiable sentence.

VARIANCE: if the agent always reaches for the same shape — and an LLM asked freely will, because its
priors are stable — then every measurement describes that one shape and there is nothing to compare.
Coverage is what turns a stream of posts into an experiment.

Selection is LEAST-SAMPLED-FIRST, deterministically. That is deliberate rather than a placeholder:
with a handful of posts no cell has enough signal to rank, and an agent that "exploits" on n=1 is
just amplifying noise into a durable lesson. Coverage first; ranking becomes meaningful only once
`MIN_SAMPLES_TO_RANK` observations exist per cell, and that decision belongs to the curator (step 4)
which can see outcomes — not to this module, which only decides what to try next.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# The asset kinds worth varying across. Deliberately a subset of everything `plan.route_for` accepts:
# these are the shapes that produce a genuinely different POST, not merely a different renderer.
ASSET_KINDS: tuple[str, ...] = ("comparison", "definition", "numbered", "mechanism",
                                "statement", "concept", "poster")

# Fallback pillars if the brand has not declared any. Generic on purpose — a real brand's pillars
# come from its positioning row, and inventing specific ones here would silently impose strategy.
DEFAULT_PILLARS: tuple[str, ...] = ("education", "mechanism", "myth-correction")

# Below this many observations a cell cannot be ranked against another; the loop stays in coverage.
MIN_SAMPLES_TO_RANK = 5


@dataclass(frozen=True)
class Cell:
    asset_kind: str
    pillar: str

    def as_choices(self) -> dict[str, str]:
        return {"asset_kind": self.asset_kind, "pillar": self.pillar}


def cells(pillars: tuple[str, ...] | list[str]) -> list[Cell]:
    """Every combination worth trying. Order is stable so selection is reproducible."""
    ps = tuple(pillars) or DEFAULT_PILLARS
    return [Cell(k, p) for p in ps for k in ASSET_KINDS]


def next_cell(pillars: tuple[str, ...] | list[str], recent: list[dict]) -> Cell:
    """Pick the least-sampled cell, breaking ties by matrix order.

    `recent` is the recent campaigns' `choices` dicts. Counting only recent history rather than all
    time is what lets the matrix re-explore after a strategy change — an all-time count would let
    early posts dominate the schedule forever.
    """
    grid = cells(pillars)
    counts: dict[tuple[str, str], int] = {(c.asset_kind, c.pillar): 0 for c in grid}
    for r in recent or []:
        key = (str((r or {}).get("asset_kind", "")), str((r or {}).get("pillar", "")))
        if key in counts:
            counts[key] += 1
    # min() over the stable grid order gives a deterministic winner among equally-unsampled cells.
    return min(grid, key=lambda c: (counts[(c.asset_kind, c.pillar)], grid.index(c)))


def coverage(pillars: tuple[str, ...] | list[str], recent: list[dict]) -> dict[str, Any]:
    """How much of the matrix has been tried, and whether anything is rankable yet.

    Surfaced so the loop can say "still exploring" honestly instead of implying it has learned
    something from three posts.
    """
    grid = cells(pillars)
    counts: dict[tuple[str, str], int] = {(c.asset_kind, c.pillar): 0 for c in grid}
    for r in recent or []:
        key = (str((r or {}).get("asset_kind", "")), str((r or {}).get("pillar", "")))
        if key in counts:
            counts[key] += 1
    sampled = sum(1 for v in counts.values() if v)
    return {
        "cells": len(grid),
        "sampled": sampled,
        "unsampled": len(grid) - sampled,
        "rankable": sum(1 for v in counts.values() if v >= MIN_SAMPLES_TO_RANK),
        "exploring": sampled < len(grid) or not any(v >= MIN_SAMPLES_TO_RANK for v in counts.values()),
    }


def directive(cell: Cell) -> str:
    """The instruction handed to the ideator, as a constraint rather than a suggestion.

    Phrased to bind the SHAPE and the TOPIC AREA while leaving the actual idea free — the point is
    to vary deliberately, not to dictate the content.
    """
    return (f"\nTODAY'S ASSIGNMENT (binding): make a '{cell.asset_kind}' post in the "
            f"'{cell.pillar}' pillar. Set asset_kind to exactly '{cell.asset_kind}'. The specific "
            f"idea is yours, but the shape and the pillar are fixed — this run is filling a gap in "
            f"a deliberate content matrix, so choosing a different shape defeats the experiment.\n")
