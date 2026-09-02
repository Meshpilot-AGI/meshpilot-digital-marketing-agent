"""Conscience (DELIBERATION Phase 2) — an INDEPENDENT critic checks a run's outward-intended output
against a written constitution (`agent/CONSCIENCE.md`) before it reaches a human.

Not self-grading: this is a separate model call with a FRESH context — it never sees the actor's
transcript or reasoning, only the proposed output and the constitution — so the author can't
rationalize its own work past the check (self-critique by the same context is gameable). Advisory for
now: the verdict annotates the episode and is surfaced to the human reviewing the draft; it blocks
nothing, because publishing is drafts-only. When outward actions (publish/spend/reply) are enabled
later, the same critic becomes a pre-commit HARD gate on those specific tools.

One model call on the loop model (or AGENT_DELIBERATION_MODEL), wrapped so it can never fail the run. Gated by `agent_conscience_enabled`
(default off) at the runner.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from functools import lru_cache
from typing import Awaitable, Callable

import structlog

from glitch_signal.agent.loop import llm as agent_llm

log = structlog.get_logger(__name__)

CompleteFn = Callable[..., Awaitable[str]]


# The critic is the last gate before anything reaches the public, so it runs on the CRITICAL tier —
# the strongest model available, with the router's fallbacks behind it.
#
# It previously pinned a model instead, which had two costs beyond capability. Passing `model=` to
# `complete()` overrides the tier entirely (`_resolve_models` returns just that one model), so the
# critic also lost the router's cross-provider failover: if that single model was rate-limited the
# review returned {} and — correctly, but expensively — every post was held. And the pinned id was a
# date-suffixed variant, which is not a form the API guarantees.
CRITIC_TIER = "critical"


def _model() -> str | None:
    """An explicit override, or None to let the router pick the CRITICAL tier.

    `AGENT_DELIBERATION_MODEL` remains an escape hatch for pinning a specific model, but it is no
    longer the default path — an unset variable now means "use the best available", not "use
    whatever the loop happens to use".
    """
    return (os.environ.get("AGENT_DELIBERATION_MODEL") or "").strip() or None


# Sits beside SOUL.md in the agent package (parents[1] == …/agent from …/agent/loop/).
_CONSTITUTION_PATH = pathlib.Path(__file__).resolve().parents[1] / "CONSCIENCE.md"

_VERDICTS = ("pass", "concerns", "escalate")

# The positioning doc is front-loaded with identity and back-loaded with PROHIBITIONS (claim limits,
# banned register, banned imagery). A tight budget here silently truncates exactly the half the
# critic exists to enforce — at 3000 chars it was cut before reaching "no outcome promises".
_POSITIONING_BUDGET = 8000

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


async def brand_facts(brand_id: str, *, limit: int = 8) -> str:
    """Recall the brand's VERIFIED facts (kind=fact) as ground truth to hand the critic. '' on failure.

    Feeding the critic verified facts does NOT compromise its independence — independence is about not
    seeing the AUTHOR's reasoning/transcript, not about withholding ground truth. Facts let it confirm
    real claims (and stop escalating a genuine brand it happens to be unfamiliar with)."""
    try:
        from glitch_signal.agent.memory.store import is_verified_provenance
        from glitch_signal.agent.memory.store import recall as mem_recall
        # The recall QUERY already restricts to operator-verified provenance, so `limit` applies to the
        # filtered set (verified facts aren't dropped by a pre-filter row cap). Re-check in Python as
        # defense in depth: trust comes from typed verification metadata / a reserved EXACT source,
        # NEVER from arbitrary source substrings — an agent- or curator-written "fact" (source=agent_loop
        # / curator) can't pass as verified and so can't suppress a critic escalation.
        mems = await mem_recall(brand_id, "brand identity product features audience pricing",
                                k=limit, kinds=["fact"], verified_only=True)
        verified = [m for m in mems if is_verified_provenance(m.source, getattr(m, "metadata", None))]
        return "\n".join(f"- {m.content}" for m in verified[:limit])[:2500]
    except Exception:  # noqa: BLE001 — no facts → the critic just reviews without ground truth
        log.warning("agent.conscience.brand_facts_failed")   # sanitized: no exception detail in logs
        return ""


async def review(goal: str, output: str | None, *, facts: str = "", positioning: str = "",
                 complete: CompleteFn | None = None, model: str | None = None) -> dict:
    """Independently review the run's outward-intended output. {} if no constitution / empty output.

    `facts` (verified brand ground truth) is authoritative: the critic must defer to it over its own
    priors — so it stops escalating a real brand it's simply unfamiliar with (e.g. a name collision).

    `positioning` is kept SEPARATE from facts on purpose. Facts are checkable claims; positioning is
    judgement — voice, and the never-say list. Mislabelling judgement as ground truth would let a
    positioning statement launder itself into an authorized claim. The critic needs both, but it
    must know which is which: facts say what is TRUE, positioning says what is ON-BRAND, and an
    output can satisfy one while violating the other."""
    complete = complete or agent_llm.complete
    con = constitution()
    text = (output or "").strip()
    if not con or not text:
        return {}
    system = _SYS_PREFIX + con[:4000]
    facts_block = ""
    if facts.strip():
        facts_block = (
            "\n\n--- VERIFIED BRAND FACTS (operator-verified ground truth) ---\n" + facts[:2500] +
            "\nThese facts establish the brand's identity and offering — rely on them to avoid a false "
            "alarm about an unfamiliar brand or a name collision. They do NOT authorize any claim: STILL "
            "escalate if the output makes a harmful, non-compliant, misleading, or unsupported claim, or "
            "asserts something these facts do not support.")
    pos_block = ""
    if positioning.strip():
        pos_block = (
            "\n\n--- BRAND POSITIONING (voice + prohibitions; NOT claim authorization) ---\n"
            + positioning[:_POSITIONING_BUDGET] +
            "\nESCALATE if the output breaks a prohibition named here, adopts a voice this forbids, or "
            "positions the brand as something it explicitly says it is not — even when every individual "
            "statement in the output is factually true.")
    prompt = (f"Run goal (context only): {goal}\n\nProposed output to review:\n{text[:3000]}"
              f"{facts_block}{pos_block}\n\nYour verdict JSON:")
    try:
        raw = await complete(prompt, system=system, model=model or _model(),
                             tier=CRITIC_TIER, timeout_s=40)
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
