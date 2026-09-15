"""Title + location filtering from the brand's `jobs` config.

Recall-first: this runs BEFORE any LLM sees a posting, so it must be cheap and conservative. A
posting wrongly dropped here is never scored, never offered, and never noticed — so the rules bias
toward letting a borderline posting through and letting the score floor (4.3) reject it later.

Two asymmetries that matter, both learned from the operator's career-ops run on 2026-09-14:

1. An EMPTY location passes. Many ATS boards omit the field entirely; penalizing missing data drops
   real roles for no signal.
2. An exclude match beats an include match. "Senior Product Marketing Manager" contains "Marketing
   Manager"; without exclusion-wins it would be queued as a target role, and Product Marketing is a
   different discipline. 28% of the operator's first scan was exactly this.
"""
from __future__ import annotations

import re

_WORD_CACHE: dict[str, re.Pattern[str]] = {}


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _all_words_present(haystack: str, needle: str) -> bool:
    """Every word of a MULTI-word needle appears in the haystack, in any order.

    Substring matching cannot see word-order variants, and job titles are full of them:
    "Manager, Marketing" is the same job as "Marketing Manager" and was being dropped. Measured on
    Job Bank, where inverted NOC-style titles are common.

    Order-independence is safe here because exclusions are checked FIRST and win — "Product
    Marketing Manager" is rejected by the exclude list before this ever runs.
    """
    words = [w for w in _norm(needle).split() if w]
    if len(words) < 2:
        return False
    hay = f" {haystack} "
    return all(_contains(hay, w) for w in words)


def _contains(haystack: str, needle: str) -> bool:
    """Case-insensitive substring, but whole-word for short needles.

    A bare 2-3 letter keyword ("AI", "PPC", "CRO") matches inside unrelated words — "AI" fires on
    "Maintenance", "CRO" on "Microsoft". Anchor those to word boundaries; leave longer ones loose so
    "Marketing" still reaches "Marketing Manager".
    """
    n = _norm(needle)
    if not n:
        return False
    if len(n) <= 3:
        pat = _WORD_CACHE.get(n)
        if pat is None:
            pat = _WORD_CACHE[n] = re.compile(rf"(?<!\w){re.escape(n)}(?!\w)")
        return bool(pat.search(haystack))
    return n in haystack


def title_ok(title: str | None, cfg: dict) -> tuple[bool, str]:
    """(passes, reason). Exclusions win over inclusions."""
    t = _norm(title)
    if not t:
        return False, "no title"
    for bad in cfg.get("exclude_titles") or []:
        if _contains(t, bad):
            return False, f"excluded: {bad}"
    includes = cfg.get("target_titles") or []
    if not includes:
        return True, "no target_titles configured — all titles pass"
    for good in includes:
        if _contains(t, good):
            return True, f"matched: {good}"
    for good in includes:
        if _all_words_present(t, good):
            return True, f"matched (word-order variant): {good}"
    return False, "no target title matched"


def location_ok(location: str | None, cfg: dict) -> tuple[bool, str]:
    """(passes, reason). An empty location PASSES — missing data is not a signal."""
    loc = _norm(location)
    if not loc:
        return True, "no location given"
    locs = cfg.get("locations") or {}
    allow = locs.get("allow") or []
    if not allow:
        return True, "no location allow-list configured"
    for a in allow:
        if _contains(loc, a):
            return True, f"matched: {a}"
    return False, "outside allowed locations"


def passes(title: str | None, location: str | None, cfg: dict) -> tuple[bool, str]:
    ok, why = title_ok(title, cfg)
    if not ok:
        return False, why
    ok, why_loc = location_ok(location, cfg)
    if not ok:
        return False, why_loc
    return True, f"{why}; {why_loc}"
