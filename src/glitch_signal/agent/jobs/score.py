"""Two-pass scoring — an A-H report and a 1-5 score per listing.

The two-pass rule, borrowed from career-ops (design § 2), is the whole point and the generation
ORDER is the mechanism:

    Pass 1 — read the JD ALONE. Extract its requirements and rate each one's IMPORTANCE to this
             posting. The CV is not in context.
    Pass 2 — then read the CV and rate the MATCH per requirement. Importance is never revised.

A single-pass scorer anchors: a model that has just written "strong match" is pulled toward calling
that requirement important, and toward discounting what the candidate lacks. That inverts the
feature — you want to know what the JOB needs, not a flattering re-description of the candidate.

Work authorization is NOT scored by the model (see workauth.py): it is a factual question with a
right answer, decided deterministically and merged in afterwards.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from glitch_signal.agent.jobs import workauth

log = structlog.get_logger()

MAX_JD_CHARS = 12000
MAX_CV_CHARS = 8000
# A 12-18 requirement posting with verbatim evidence does NOT fit the 2048-token default.
# 8000, not 12000. OpenRouter RESERVES credit against max_tokens per request, so a larger budget
# drains the balance faster than the tokens actually used — that is what brought a 402 forward
# mid-sweep. The pass-2 overflow it was raised to fix is already handled by capping requirements at
# _MAX_REQS; the bigger budget was belt-and-braces that cost real money.
_MAX_TOKENS = 8000
_MAX_REQS = 18   # keep pass 2's JSON inside the budget; see the ranking note below
_IMPORTANCE_ORDER = {"critical": 0, "high": 1, "meaningful": 2, "preferred": 3, "low_signal": 4}

_PASS1_SYSTEM = (
    "You are reading a job posting to extract what THE EMPLOYER is asking for. "
    "You have NOT seen any candidate. Do not speculate about one. "
    "Rate each requirement's importance TO THIS POSTING only."
)

_PASS1_PROMPT = """Read this job posting and extract its requirements.

For each requirement return:
  requirement  — a short phrase, in the posting's own language where possible
  jd_signal    — the verbatim phrase from the posting that evidences it (quote, never paraphrase)
  importance   — one of: critical | high | meaningful | preferred | low_signal

`critical` = an explicit must-have, the title itself, a core responsibility, a required
language/credential. `low_signal` = generic boilerplate.

Return STRICT JSON only:
{{"role_summary": "...", "requirements": [{{"requirement": "...", "jd_signal": "...", "importance": "..."}}]}}

JOB POSTING:
{jd}
"""

_PASS2_SYSTEM = (
    "You are matching a candidate's CV against requirements that were already extracted and already "
    "rated for importance. You MUST NOT change any importance value. "
    "Judge only how well the CV evidences each requirement. "
    "Never invent experience the CV does not state. If the CV is silent, say so."
)

_PASS2_PROMPT = """Here are the posting's requirements, with importance ALREADY fixed. Do not change them.

{requirements}

Here is the candidate's CV:

{cv}

For each requirement, add:
  match     — one of: strong | partial | none
  evidence  — what in the CV supports it, or the gap if none. Quote the CV; never invent.

Then give an overall score from 1.0 to 5.0 (one decimal) and a two-sentence verdict.

SCORING ANCHORS — use these, and do NOT compute a fraction of requirements matched:
  5.0  Exceptional fit. Strong on every critical requirement; would be top of the stack.
  4.5  Strong fit. Every critical requirement evidenced; gaps are peripheral.
  4.0  CREDIBLE CANDIDATE — a hiring manager would interview them. The core of the job is
       evidenced; remaining gaps are peripheral or learnable (one ad platform, a reporting tool,
       a named process, domain familiarity).
  3.0  Partial fit. Something genuinely CENTRAL to the role is missing or unevidenced.
  2.0  Wrong track. Adjacent discipline; the core of this job is not what they do.
  1.0  Unrelated.

Weight CRITICAL and HIGH requirements far above preferred/low_signal ones. A candidate who is strong
on the core of the job must NOT be dragged below 4.0 by peripheral gaps — missing one ad platform
among several, an unnamed dashboard tool, or a process they have plainly done under another name is
not evidence against them. Conversely, do not inflate: a missing CRITICAL requirement is worth more
than several matched preferred ones.

Return STRICT JSON only:
{{"requirements": [{{"requirement": "...", "importance": "...", "match": "...", "evidence": "..."}}],
  "score": 0.0, "verdict": "...", "strengths": ["..."], "gaps": ["..."]}}
"""


def _json_from(text: str) -> dict:
    """Parse a model's JSON, tolerating fences and prose around it. Returns {} on failure."""
    if not text:
        return {}
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return {}


def _clamp_score(raw: Any) -> float | None:
    try:
        s = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(5.0, round(s, 1)))


def _report_md(listing: dict, pass1: dict, pass2: dict, wa: dict, score: float | None) -> str:
    rows = []
    for r in pass2.get("requirements") or []:
        rows.append("| {} | {} | {} | {} |".format(
            str(r.get("requirement", ""))[:80].replace("|", "/"),
            r.get("importance", ""), r.get("match", ""),
            str(r.get("evidence", ""))[:160].replace("|", "/")))
    flag = ""
    if wa.get("hard_stop"):
        flag = (f"\n⛔ **No sponsorship:** JD states \"{wa.get('evidence')}\" "
                f"and the role is outside your authorized locations.\n")
    return (
        f"# {listing.get('title') or 'Untitled'} — {listing.get('company') or 'Unknown'}\n\n"
        f"**URL:** {listing.get('canonical_url')}\n"
        f"**Location:** {listing.get('location') or 'not stated'}\n"
        f"**Score:** {score if score is not None else 'n/a'}/5\n"
        f"**Work authorization:** {wa.get('verdict')} — {wa.get('reason')}\n"
        f"{flag}\n"
        f"## A — Role summary\n\n{pass1.get('role_summary', '')}\n\n"
        f"## B — Requirements (importance fixed in pass 1, match added in pass 2)\n\n"
        "| Requirement | Importance | Match | Evidence / gap |\n|---|---|---|---|\n"
        + ("\n".join(rows) if rows else "| _none extracted_ | | | |") + "\n\n"
        f"## C — Verdict\n\n{pass2.get('verdict', '')}\n\n"
        "## D — Strengths\n\n" + "\n".join(f"- {s}" for s in (pass2.get("strengths") or []) ) + "\n\n"
        "## E — Gaps\n\n" + "\n".join(f"- {g}" for g in (pass2.get("gaps") or []) ) + "\n\n"
        f"## F — Job description (archived verbatim)\n\n{(listing.get('jd_text') or '')[:MAX_JD_CHARS]}\n"
    )


async def score_listing(listing: dict, cv_text: str, cfg: dict, *, tier: str = "complex") -> dict:
    """Score one listing. Returns {score, score_parts, work_auth, report_md, model, hard_stop}."""
    from glitch_signal.agent.loop import llm

    jd = (listing.get("jd_text") or "")[:MAX_JD_CHARS]
    wa = workauth.classify(jd, listing.get("location"), cfg)

    if not jd.strip():
        # No JD text means nothing to score against. Returning a low score would be a fabricated
        # judgement; return None and let the caller re-fetch or skip.
        return {"score": None, "score_parts": {}, "work_auth": wa["verdict"], "hard_stop": wa["hard_stop"],
                "report_md": None, "model": None, "error": "no jd_text archived for this listing"}

    # PASS 1 — JD only. The CV is deliberately absent from this call's context.
    p1_raw = await llm.complete_messages(
        [{"role": "system", "content": _PASS1_SYSTEM},
         {"role": "user", "content": _PASS1_PROMPT.format(jd=jd)}],
        tier=tier, max_tokens=_MAX_TOKENS)
    pass1 = _json_from(p1_raw)
    reqs = pass1.get("requirements") or []
    if not reqs:
        return {"score": None, "score_parts": {}, "work_auth": wa["verdict"], "hard_stop": wa["hard_stop"],
                "report_md": None, "model": None, "error": "pass 1 extracted no requirements"}

    # PASS 2 — CV against requirements whose importance is already fixed.
    # A 23-requirement posting overran even an 8000-token pass 2 and returned unparseable JSON
    # (measured on a real listing). Cap the list by IMPORTANCE rather than truncating the JSON
    # mid-object: dropping the least important requirements is a defensible loss; dropping whatever
    # happened to be last is not.
    ranked = sorted(reqs, key=lambda r: _IMPORTANCE_ORDER.get(str(r.get("importance", "")).lower(), 9))
    sent = ranked[:_MAX_REQS]
    p2_raw = await llm.complete_messages(
        [{"role": "system", "content": _PASS2_SYSTEM},
         {"role": "user", "content": _PASS2_PROMPT.format(
             requirements=json.dumps(sent, indent=1)[:9000], cv=cv_text[:MAX_CV_CHARS])}],
        tier=tier, max_tokens=_MAX_TOKENS)
    pass2 = _json_from(p2_raw)
    # A pass-2 that produced no parseable JSON must FAIL LOUDLY. Returning score=None with no error
    # reads as "scored, badly" and would silently bury every role. (Observed live: an 18-requirement
    # posting overran the default 2048-token budget, truncating the JSON mid-object.)
    if not pass2:
        return {"score": None, "score_parts": {}, "work_auth": wa["verdict"], "hard_stop": wa["hard_stop"],
                "report_md": None, "model": None,
                "error": f"pass 2 returned no parseable JSON ({len(p2_raw or '')} chars)"}

    # Importance is pass 1's answer. If pass 2 changed any, restore it — the rule is the mechanism,
    # not a suggestion, and a model that silently re-rates importance has undone the whole design.
    fixed = {str(r.get("requirement", "")).strip().lower(): r.get("importance") for r in reqs}
    overridden = 0
    for r in pass2.get("requirements") or []:
        key = str(r.get("requirement", "")).strip().lower()
        if key in fixed and r.get("importance") != fixed[key]:
            r["importance"] = fixed[key]
            overridden += 1
    if overridden:
        log.warning("jobs.score.importance_overridden", n=overridden,
                    url=listing.get("canonical_url"))

    score = _clamp_score(pass2.get("score"))
    parts = {"critical": sum(1 for r in reqs if r.get("importance") == "critical"),
             "requirements": len(reqs),
             "strong": sum(1 for r in (pass2.get("requirements") or []) if r.get("match") == "strong"),
             "none": sum(1 for r in (pass2.get("requirements") or []) if r.get("match") == "none"),
             "work_auth": wa["verdict"],
             "importance_overridden": overridden}

    return {"score": score, "score_parts": parts, "work_auth": wa["verdict"],
            "hard_stop": wa["hard_stop"], "report_md": _report_md(listing, pass1, pass2, wa, score),
            "model": None, "error": None}


MIN_REQUIREMENTS_FOR_CONFIDENCE = 8


def meets_floor(score: float | None, hard_stop: bool, cfg: dict, default_floor: float = 4.0,
                *, parts: dict | None = None) -> bool:
    """Operator decision 2: below the floor a role is SKIPPED, never offered for a yes/no.

    A THIN posting cannot clear the floor. Measured 2026-09-15: the single highest score in a
    28-role sweep (4.0) came from a job description that yielded FOUR requirements and zero
    criticals — there was almost nothing to fail, so the score says more about the posting's length
    than about the candidate. Treating that as the best opportunity available would put the operator
    in front of an employer on the strength of a scoring artifact.

    This is deliberately a CONFIDENCE gate, not a penalty: the score is left untouched and reported
    honestly, but a posting we could not really evaluate does not get offered.
    """
    if hard_stop or score is None:
        return False
    n = int((parts or {}).get("requirements") or 0)
    if parts is not None and n < MIN_REQUIREMENTS_FOR_CONFIDENCE:
        return False
    return score >= float((cfg or {}).get("min_score") or default_floor)
