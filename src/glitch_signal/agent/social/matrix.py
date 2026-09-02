"""The content matrix — deliberate variation, so outcomes are attributable.

Recording the CHOICES (asset kind x pillar) alongside `social_post_metric` gives outcome analysis
something to group by; without it "comparison posts land well" is unfalsifiable. Left to itself an
LLM's priors are stable, so it keeps reaching for the same shape — coverage across cells is what
turns a stream of posts into an experiment.

Selection is least-sampled-first, deterministically: with few posts no cell has enough signal to
rank, and "exploiting" on n=1 just amplifies noise into a durable lesson. Ranking (once
`MIN_SAMPLES_TO_RANK` observations exist per cell) is the curator's call, not this module's — this
module only decides what to try next.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Subset of what `plan.route_for` accepts — shapes that produce a genuinely different post, not
# merely a different renderer.
ASSET_KINDS: tuple[str, ...] = ("comparison", "definition", "numbered", "mechanism",
                                "statement", "concept", "poster")

# Fallback if a brand hasn't declared pillars. Generic on purpose — inventing specifics here would
# silently impose strategy that should come from the brand's positioning row.
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

    `recent` (not all-time) lets the matrix re-explore after a strategy change instead of letting
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
    """How much of the matrix has been tried and whether anything is rankable yet — lets the loop
    say "still exploring" honestly instead of implying it learned something from three posts."""
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
    """The instruction handed to the ideator: binds shape and pillar, leaves the idea itself free."""
    return (f"\nTODAY'S ASSIGNMENT (binding): make a '{cell.asset_kind}' post in the "
            f"'{cell.pillar}' pillar. Set asset_kind to exactly '{cell.asset_kind}'. The specific "
            f"idea is yours, but the shape and the pillar are fixed — this run is filling a gap in "
            f"a deliberate content matrix, so choosing a different shape defeats the experiment.\n")
