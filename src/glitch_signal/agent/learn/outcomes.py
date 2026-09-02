"""Revise strategy from MEASURED outcomes — the step that closes the loop.

`curator.py` distils the agent's own record of what it did, producing lessons about intentions only.
This curator reads `social_post_metric` joined to each campaign's `choices`, so its lessons are about
what actually happened.

Below the ranking threshold this writes nothing and says so, rather than hedging — a durable lesson
shapes every future post and looks identical to a founded one once written, so an unfounded one
compounds rather than decaying.

Lessons are `kind='fact'` with a stable `perf:` key (re-running updates, not duplicates) and
`source='curator'`, which deliberately does not satisfy the operator-verified gate — a self-derived
lesson can never be quoted as ground truth by the conscience critic, only surfaced as an
unverified note.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

import structlog

log = structlog.get_logger(__name__)

SYSTEM = (
    "You analyse an autonomous marketing agent's MEASURED post performance for one brand. You are "
    "given per-cell means with sample sizes. Write only conclusions the samples support; prefer "
    "fewer, sharper lessons. Never invent a number, never generalise from a single cell, and never "
    "claim a cause — the data is observational and confounded by posting time. Output ONLY a JSON "
    'array of {"key": "<short-stable-slug>", "content": "<one durable lesson, including the sample '
    'size it rests on>", "importance": <0..1>} — at most 3 items, no prose, no fences.'
)

_ASK = (
    "{evidence}\n\n"
    "Write the durable lessons this evidence supports for future content decisions. Each lesson "
    "must name the sample size it rests on. JSON array only."
)


def _parse(raw: str) -> list[dict]:
    s = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b == -1:
        return []
    try:
        v = json.loads(s[a:b + 1])
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


def _clamp_importance(value: Any, *, default: float = 0.5) -> float:
    """Clamp untrusted LLM-provided importance to the finite 0..1 range — a non-numeric, NaN/inf, or
    out-of-range value reaching `remember` would silently distort recall ordering forever."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(0.0, min(1.0, f))


async def curate_performance(brand_id: str, *, by_cell: Any = None, complete: Any = None,
                             remember: Any = None, engine: Any = None) -> dict:
    """Distil measured performance into durable lessons — or decline, explicitly. `wrote: 0` with a
    reason is a correct, expected outcome for most of this loop's life."""
    from glitch_signal.agent.social import performance as _perf

    by_cell = by_cell or _perf.by_cell
    try:
        cells = await by_cell(brand_id, engine=engine)
    except _perf.PerformanceQueryError as exc:
        # Distinct from "insufficient evidence" — an outage must not be reported as "looked, found
        # nothing", or it hides indefinitely.
        log.warning("learn.performance_query_failed", brand_id=brand_id, error=str(exc)[:200])
        return {"wrote": 0, "reason": "performance query failed"}
    summary = _perf.summarise(cells)

    if not summary["can_conclude"]:
        log.info("learn.performance_insufficient", brand_id=brand_id,
                 observed=summary["cells_observed"], rankable=summary["cells_rankable"])
        return {"wrote": 0, "reason": "insufficient evidence",
                "cells_observed": summary["cells_observed"],
                "cells_rankable": summary["cells_rankable"],
                "min_samples_to_rank": summary["min_samples_to_rank"]}

    if complete is None:
        from glitch_signal.agent.loop import llm as agent_llm
        complete = agent_llm.complete
    if remember is None:
        from glitch_signal.agent.memory.store import remember as _remember

        async def remember(brand, content, key, importance):  # noqa: ANN001
            await _remember(brand, "fact", content, key=key, importance=importance,
                            source="curator")

    try:
        raw = await complete(_ASK.format(evidence=_perf.evidence_block(summary)),
                             system=SYSTEM, tier="complex", timeout_s=60)
    except Exception as exc:  # noqa: BLE001 — a curator failure must never disturb the agent
        log.warning("learn.performance_llm_failed", error=str(exc)[:200])
        return {"wrote": 0, "reason": "curator llm failed"}

    wrote = 0
    for item in _parse(raw)[:3]:
        key = str(item.get("key") or "").strip()
        content = str(item.get("content") or "").strip()
        if not key or not content:
            continue
        try:
            importance = _clamp_importance(item.get("importance", 0.5))
            await remember(brand_id, content, f"perf:{key}", importance)
            wrote += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("learn.performance_write_failed", key=key, error=str(exc)[:200])
    log.info("learn.performance", brand_id=brand_id, wrote=wrote,
             rankable=summary["cells_rankable"])
    return {"wrote": wrote, "cells_rankable": summary["cells_rankable"],
            "ranked": [f"{c['asset_kind']}×{c['pillar']}×{c.get('platform')}"
                      for c in summary["ranked"][:3]]}
