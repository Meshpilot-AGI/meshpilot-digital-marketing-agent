"""Conscience (DELIBERATION Phase 2) — an INDEPENDENT critic checks a run's outward-intended output
against a written constitution (`agent/CONSCIENCE.md`) before it reaches a human.

Not self-grading: this is a separate model call with a FRESH context — it never sees the actor's
transcript or reasoning, only the proposed output and the constitution — so the author can't
rationalize its own work past the check (self-critique by the same context is gameable). Advisory for
now: the verdict annotates the episode and is surfaced to the human reviewing the draft; it blocks
nothing, because publishing is drafts-only. When outward actions (publish/spend/reply) are enabled
later, the same critic becomes a pre-commit HARD gate on those specific tools.

One cheap model call (Haiku), wrapped so it can never fail the run. Gated by `agent_conscience_enabled`
(default off) at the runner.
"""
from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Awaitable, Callable

import structlog

from glitch_signal.agent.loop import llm as agent_llm

log = structlog.get_logger(__name__)

CompleteFn = Callable[..., Awaitable[str]]
DELIBERATION_MODEL = "claude-haiku-4-5-20251001"

# Sits beside SOUL.md in the agent package (parents[1] == …/agent from …/agent/loop/).
_CONSTITUTION_PATH = pathlib.Path(__file__).resolve().parents[1] / "CONSCIENCE.md"

_VERDICTS = ("pass", "concerns", "escalate")

_SYS_PREFIX = (
    "You are an INDEPENDENT reviewer — NOT the author of the output below and you owe it no loyalty. "
    "Judge the proposed marketing output ONLY against the constitution that follows. Reply with ONLY a "
    'JSON object: {"verdict": "pass"|"concerns"|"escalate", "notes": "<one or two lines naming the '
    'specific principle(s) at issue, or why it passes>"}.\n\n--- CONSTITUTION ---\n'
)


@lru_cache(maxsize=1)
def constitution() -> str:
    try:
        return _CONSTITUTION_PATH.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001 — no constitution file → conscience no-ops
        log.warning("agent.conscience.constitution_missing", error=str(exc)[:200])
        return ""


def _parse_obj(raw: str) -> dict:
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


async def review(goal: str, output: str | None, *, complete: CompleteFn | None = None,
                 model: str | None = None) -> dict:
    """Independently review the run's outward-intended output. {} if no constitution / empty output."""
    complete = complete or agent_llm.complete
    con = constitution()
    text = (output or "").strip()
    if not con or not text:
        return {}
    system = _SYS_PREFIX + con[:4000]
    prompt = (f"Run goal (context only): {goal}\n\nProposed output to review:\n{text[:3000]}\n\n"
              "Your verdict JSON:")
    try:
        raw = await complete(prompt, system=system, model=model or DELIBERATION_MODEL, timeout_s=40)
    except Exception as exc:  # noqa: BLE001 — deliberation must never fail the run
        log.warning("agent.conscience.review_failed", error=str(exc)[:200])
        return {}
    obj = _parse_obj(raw)
    if not obj:
        return {}
    verdict = str(obj.get("verdict", "")).lower().strip()
    if verdict not in _VERDICTS:
        verdict = "concerns"   # fail toward caution on an unparseable verdict
    return {"verdict": verdict, "notes": str(obj.get("notes", ""))[:400]}
