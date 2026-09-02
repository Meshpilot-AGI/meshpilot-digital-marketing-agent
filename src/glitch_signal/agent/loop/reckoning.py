"""Reckoning (DELIBERATION Phase 1) — expectation before acting, honest self-assessment after.

Before a run acts it records a one-line EXPECTATION (what it intends to produce + what success looks
like) — a real pre-commitment, not hindsight. After the run it compares that expectation to what
ACTUALLY happened (the action transcript + any tool errors) and produces a short self-assessment with
a fault attribution when it fell short. It is grounded only in the run's own evidence, so it is tagged
`trust="self-assessed"` and is NEVER treated as a verified signal — external grounding (approval,
engagement) is a later phase. Advisory only: it annotates the episode (so LEARN can curate patterns of
self-flagged misses) and is surfaced to the human reviewer; it blocks nothing.

One model call each on the loop model by default (`AGENT_DELIBERATION_MODEL` can point it at a cheaper
model like Haiku once that key's access is confirmed), and every call is wrapped so deliberation can
never fail the run. Gated by `agent_reckoning_enabled` (default off) at the runner.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Awaitable, Callable

import structlog

from glitch_signal.agent.loop import llm as agent_llm

log = structlog.get_logger(__name__)

CompleteFn = Callable[..., Awaitable[str]]


# Deliberation is judgement, so it routes rather than pinning a model — a pinned `model=` overrides
# the tier entirely and forfeits the router's cross-provider failover.
DELIBERATION_TIER = "complex"


def _model() -> str:
    """Model for the deliberation passes. `AGENT_DELIBERATION_MODEL` overrides; otherwise the SAME
    model the main loop uses. Reflection is cheap legwork so a Haiku is ideal — but not every key/org
    can call every model (the cloud key couldn't call Haiku 4.5, which silently emptied these passes),
    so the safe default is the loop model, and Haiku is opt-in via the env var once its access is confirmed."""
    return (os.environ.get("AGENT_DELIBERATION_MODEL") or "").strip() or agent_llm._model(None)


def _parse_obj(raw: str) -> dict:
    """First JSON object in the model output (mirrors the LEARN curator's tolerant parse)."""
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    for candidate in ([m.group(0)] if m else []) + [raw]:
        try:
            val = json.loads(candidate)
            if isinstance(val, dict):
                return val
        except Exception:  # noqa: BLE001
            continue
    return {}


_EXPECT_SYS = (
    "You are the autonomous marketing agent pausing to think BEFORE you act. In one or two sentences, "
    "state what you expect this run to produce and what a good outcome looks like. Be concrete and "
    "honest — this is a prediction you will later be judged against, not a summary."
)


async def expectation(goal: str, seed: str, *, complete: CompleteFn | None = None,
                      model: str | None = None) -> str:
    """One-line expectation captured BEFORE the run acts (foresight, not hindsight). '' on failure."""
    complete = complete or agent_llm.complete
    prompt = f"Goal: {goal}\n\nWhat you recall:\n{(seed or '')[:1500]}\n\nYour expectation:"
    try:
        txt = await complete(prompt, system=_EXPECT_SYS, model=model or _model(),
                             tier=DELIBERATION_TIER, timeout_s=40)
        return (txt or "").strip()[:400]
    except Exception as exc:  # noqa: BLE001 — deliberation must never fail the run
        log.warning("agent.reckoning.expectation_failed", error=str(exc)[:200])
        return ""


_RECKON_SYS = (
    "You are the SAME agent reviewing your OWN completed run, honestly. Compare what you EXPECTED to "
    "what ACTUALLY happened (the action transcript and final result). Reply with ONLY a JSON object: "
    '{"met": "yes"|"no"|"unknown", "discrepancy": "<one line, or empty>", '
    '"attribution": "my-plan"|"my-belief"|"external"|"tool-failure"|"none", '
    '"lesson": "<one concrete line for next time, or empty>"}. '
    "Do not flatter yourself; if you fell short, say so and name the real cause."
)


async def reckon(goal: str, expectation_text: str, transcript: list[dict[str, Any]],
                 final: str | None, *, complete: CompleteFn | None = None,
                 model: str | None = None) -> dict:
    """Post-run self-assessment vs the recorded expectation. `trust` is always 'self-assessed'."""
    complete = complete or agent_llm.complete
    actions = "; ".join(f"{t.get('action')}→{str(t.get('observation'))[:80]}"
                        for t in (transcript or [])[:12])
    prompt = (f"Goal: {goal}\nExpected: {expectation_text or '(none recorded)'}\n"
              f"Actions: {actions or 'none'}\nFinal result: {(final or '')[:600]}\n\nYour reckoning JSON:")
    try:
        raw = await complete(prompt, system=_RECKON_SYS, model=model or _model(),
                             tier=DELIBERATION_TIER, timeout_s=40)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.reckoning.reckon_failed", error=str(exc)[:200])
        return {}
    obj = _parse_obj(raw)
    if not obj:
        return {}
    met = str(obj.get("met", "unknown")).lower()
    if met not in ("yes", "no", "unknown"):
        met = "unknown"
    return {
        "expected": expectation_text or "",
        "met": met,
        "discrepancy": str(obj.get("discrepancy", ""))[:300],
        "attribution": str(obj.get("attribution", "none")),
        "lesson": str(obj.get("lesson", ""))[:300],
        "trust": "self-assessed",   # grounded only in the run's own evidence — never a verified signal
    }
