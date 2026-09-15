"""CV tailoring — reorder, reframe, emphasise. Never invent.

Design § 5. The model is told the rule, and then the rule is ENFORCED by `verify.py` regardless of
what the model did. Both halves matter: the instruction makes compliance likely, the verifier makes
violation impossible to ship. Prompting alone is not a control.

The output is markdown, from the operator's own master CV. Nothing is sourced from memory, from a
previous tailored CV, or from anywhere outside the fact base.
"""
from __future__ import annotations

import structlog

from glitch_signal.agent.jobs import verify as _verify

log = structlog.get_logger()

_MAX_TOKENS = 6000

_SYSTEM = (
    "You tailor an existing CV to a specific job posting. You may REORDER, REFRAME, EMPHASISE and "
    "CUT. You may NOT invent. Every number, employer, job title, tool, credential and date in your "
    "output must already appear in the CV you were given. If the CV does not evidence something the "
    "posting asks for, leave it out — do not soften it, approximate it, or infer it. "
    "Writing a plausible number you were not given is the single worst thing you can do here: it is "
    "a lie told in the candidate's name that they will have to defend in an interview. "
    "Output ONLY the tailored CV in markdown. No preamble, no commentary."
)

_PROMPT = """Tailor this CV for the posting below.

Rules:
- Lead with the experience this posting actually asks for.
- Keep every number EXACTLY as written in the source CV.
- Do not add employers, titles, tools, certifications or dates that are not in the source.
- Keep it to roughly the same length. Cutting is fine; padding is not.

=== TARGET POSTING ===
{jd}

=== SOURCE CV (the only permitted source of facts) ===
{cv}
"""


async def tailor_cv(listing: dict, cv_text: str, *, tier: str = "complex",
                    max_attempts: int = 2) -> dict:
    """Tailor the CV for one listing, then VERIFY it. Returns {ok, markdown, findings, attempts}.

    On a verification failure the model is given its own findings and asked once more. If it fails
    again the result is REJECTED — no third try, no "close enough", no shipping the unverified draft.
    A retry loop that eventually gives up and ships is just a slower way to ship a fabrication.
    """
    from glitch_signal.agent.loop import llm

    jd = (listing.get("jd_text") or "").strip()
    if not jd:
        return {"ok": False, "markdown": None, "findings": ["no jd_text archived for this listing"],
                "attempts": 0}
    if not (cv_text or "").strip():
        return {"ok": False, "markdown": None, "findings": ["fact base is empty"], "attempts": 0}

    # Nouns the POSTING legitimately supplies (the target company, its product names) are allowed in
    # the output even though they are not in the CV — a tailored CV names the employer it is for.
    extra = set()
    for key in ("company", "title"):
        val = listing.get(key)
        if isinstance(val, str):
            extra |= {w.strip(".,") for w in val.split() if w[:1].isupper()}

    prompt = _PROMPT.format(jd=jd[:10000], cv=cv_text[:10000])
    findings: list[str] = []

    for attempt in range(1, max_attempts + 1):
        messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
        if findings:
            messages.append({"role": "user", "content":
                             "Your previous draft contained claims NOT present in the source CV:\n"
                             + "\n".join(f"- {f}" for f in findings)
                             + "\nRewrite it using only what the source CV states. Remove those claims."})
        md = await llm.complete_messages(messages, tier=tier, max_tokens=_MAX_TOKENS)
        result = _verify.verify(md or "", cv_text, extra_allowed=extra)
        if result.ok:
            return {"ok": True, "markdown": md.strip(), "findings": [], "attempts": attempt}
        findings = result.reasons()
        log.warning("jobs.tailor.unverified", attempt=attempt, n=len(findings),
                    url=listing.get("canonical_url"))

    return {"ok": False, "markdown": None, "findings": findings, "attempts": max_attempts}
