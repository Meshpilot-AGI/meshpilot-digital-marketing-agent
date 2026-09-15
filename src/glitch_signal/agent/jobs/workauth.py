"""Work-authorization verdict — deterministic, no LLM.

Borrowed from career-ops' Block A (design § 2). Kept OUT of the model's hands on purpose: whether a
role is legally takeable is a factual question with a right answer, and a model that "reasons" about
it will occasionally reason wrong in the expensive direction — either hiding a role the operator
could take, or surfacing one they cannot.

Four verdicts, only ONE of which blocks:

    sponsors        the JD offers sponsorship, and the role is outside authorized_in
    not_needed      the role is in an authorized country (or no sponsorship is needed at all)
    unstated        outside authorized_in and the JD says nothing — NEUTRAL, not a rejection
    no_sponsorship  the JD explicitly refuses to sponsor AND the role is outside authorized_in

The asymmetry is the point. Silence is absence of signal, not refusal: most JDs never mention
sponsorship, and treating that as a block would erase the majority of the market. Only an explicit
refusal, on a role the operator cannot take from an authorized country, is a hard stop.

The subtle case that must NOT block: "must be authorized to work in Canada" when Canada IS in
authorized_in. That is a requirement the operator MEETS — reading it as a refusal inverts the check.
"""
from __future__ import annotations

import re

SPONSORS = "sponsors"
NOT_NEEDED = "not_needed"
UNSTATED = "unstated"
NO_SPONSORSHIP = "no_sponsorship"

# Explicit refusals. Deliberately narrow: each must be unambiguous on its own, because a false
# positive here silently deletes a takeable role.
_REFUSAL = [
    r"\bno\s+visa\s+sponsorship\b",
    r"\bnot\s+(?:able|willing)\s+to\s+sponsor\b",
    r"\bunable\s+to\s+sponsor\b",
    r"\bdo(?:es)?\s+not\s+(?:offer|provide)\s+(?:visa\s+)?sponsorship\b",
    r"\bwe\s+cannot\s+sponsor\b",
    r"\bcan(?:no|')t\s+sponsor\b",
    r"\bwithout\s+(?:the\s+)?need\s+for\s+(?:visa\s+)?sponsorship\b",
    r"\bsponsorship\s+is\s+not\s+(?:available|offered|provided)\b",
    r"\bno\s+sponsorship\s+(?:available|offered|provided)\b",
]
_OFFER = [
    r"\bvisa\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b",
    r"\bwe\s+(?:will\s+)?sponsor\b",
    r"\bwilling\s+to\s+sponsor\b",
    r"\b(?:we\s+)?(?:offer|provide)\s+(?:visa\s+)?sponsorship\b",
    r"\brelocation\s+(?:assistance|support|package)\b",
]
_REFUSAL_RE = [re.compile(p, re.I) for p in _REFUSAL]
_OFFER_RE = [re.compile(p, re.I) for p in _OFFER]


def _sentence_around(text: str, start: int, end: int) -> str:
    """The sentence containing a match — quoted VERBATIM in the report, never paraphrased."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
    right = min([x for x in (text.find(".", end), text.find("\n", end)) if x != -1] or [len(text)])
    return re.sub(r"\s+", " ", text[left + 1:right + 1]).strip()[:300]


def _in_authorized(location: str | None, authorized_in: list[str]) -> bool:
    loc = (location or "").lower()
    if not loc:
        # No location stated. Treat as possibly-authorized rather than possibly-blocked: a missing
        # field is not evidence the role is abroad.
        return True
    return any(a.lower() in loc for a in authorized_in if a)


def classify(jd_text: str | None, location: str | None, cfg: dict) -> dict:
    """Return {verdict, evidence, hard_stop, reason}. `cfg` is the brand's `jobs` block."""
    wa = (cfg or {}).get("work_authorization") or {}
    authorized_in = wa.get("authorized_in") or []
    needs_sponsorship = bool(wa.get("needs_sponsorship_outside"))
    text = jd_text or ""

    inside = _in_authorized(location, authorized_in) if authorized_in else False

    if inside:
        return {"verdict": NOT_NEEDED, "evidence": None, "hard_stop": False,
                "reason": f"role location is within authorized_in ({', '.join(authorized_in)})"}
    if not needs_sponsorship:
        return {"verdict": NOT_NEEDED, "evidence": None, "hard_stop": False,
                "reason": "brand declares no sponsorship is needed"}

    for rx in _REFUSAL_RE:
        m = rx.search(text)
        if m:
            return {"verdict": NO_SPONSORSHIP, "evidence": _sentence_around(text, m.start(), m.end()),
                    "hard_stop": True,
                    "reason": "JD explicitly refuses sponsorship and the role is outside authorized_in"}
    for rx in _OFFER_RE:
        m = rx.search(text)
        if m:
            return {"verdict": SPONSORS, "evidence": _sentence_around(text, m.start(), m.end()),
                    "hard_stop": False, "reason": "JD offers sponsorship or relocation"}

    return {"verdict": UNSTATED, "evidence": None, "hard_stop": False,
            "reason": "role is outside authorized_in and the JD is silent — neutral, not a refusal"}
