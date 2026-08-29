"""Content policy — strip AI footprints from every piece of published content.

Guidance in the social-copy handbook tells the agent to write like a human; this is the deterministic
ENFORCEMENT. `strip_footprints` mechanically removes the tells that can be fixed without a rewrite
(em/en-dashes, smart quotes, ellipsis char, double-hyphen). `scan_footprints` flags the softer tells
that need a rewrite (filler words, "not only ... but also"). `enforce` does both. Applied wherever
content is generated (captions today; blogs/posts/anything as those land), and exposed to the agent
as the `polish_copy` tool so it self-checks drafts before finalizing.
"""
from __future__ import annotations

import re

# Filler/marketing-ese that reads as machine-written. Word-boundary, case-insensitive. These can't be
# auto-fixed (they need a rewrite), so they're flagged, not stripped.
_BANNED_WORDS = (
    "delve", "leverage", "foster", "harness", "underscore", "embark", "unleash", "elevate",
    "navigate", "landscape", "realm", "tapestry", "ecosystem", "seamless", "robust", "revolutionize",
    "supercharge", "unlock", "meticulous", "testament", "treasure trove", "game-changer", "game changer",
    "cutting-edge", "cutting edge", "top-notch", "world-class", "paradigm", "synergy",
)
_BANNED_PHRASES = (
    "in today's fast-paced world", "in today's digital age", "rapidly evolving", "ever-evolving",
    "when it comes to", "at the end of the day", "it's not just", "not only", "but also",
    "we've got you covered", "look no further", "the world of", "embark on a journey",
)

_BANNED_WORD_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _BANNED_WORDS) + r")\b", re.IGNORECASE)
_BANNED_PHRASE_RES = [(p, re.compile(re.escape(p), re.IGNORECASE)) for p in _BANNED_PHRASES]
_NOT_ONLY_BUT_ALSO = re.compile(r"\bnot only\b.*?\bbut also\b", re.IGNORECASE | re.DOTALL)
_DASH_RE = re.compile(r"[—–―]")  # em, en, horizontal bar — for the "any dash remains" check

_SMART = {"’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}


def strip_footprints(text: str) -> str:
    """Deterministically remove the auto-fixable AI tells. Safe on human text (a dash becomes a comma)."""
    if not text:
        return text
    for bad, good in _SMART.items():
        text = text.replace(bad, good)
    # en-dash between digits is a range → hyphen (e.g. 5–10 → 5-10)
    text = re.sub(r"(?<=\d)\s*–\s*(?=\d)", "-", text)
    # every other em/en/bar dash (and the double-hyphen tell) → a comma joining the clauses
    text = re.sub(r"\s*(?:—|–|―|--)\s*", ", ", text)
    # tidy the seams the substitution can create
    text = re.sub(r",\s*([.!?;:])", r"\1", text)   # ", ." → "."
    text = re.sub(r"\s+,", ",", text)               # " ," → ","
    text = re.sub(r",{2,}", ",", text)              # ",," → ","
    text = re.sub(r"[ \t]{2,}", " ", text)          # collapse runs of spaces
    return text.strip()


def scan_footprints(text: str) -> list[str]:
    """Return the AI tells still present (for flagging / regeneration). Empty list = clean."""
    if not text:
        return []
    found: list[str] = []
    if _DASH_RE.search(text):
        found.append("dash (em/en) present")
    for m in dict.fromkeys(w.lower() for w in _BANNED_WORD_RE.findall(text)):
        found.append(f"filler word: {m}")
    if _NOT_ONLY_BUT_ALSO.search(text):
        found.append("'not only ... but also' construction")
    for phrase, rx in _BANNED_PHRASE_RES:
        if phrase in ("not only", "but also", "it's not just"):
            continue  # covered by the construction check above
        if rx.search(text):
            found.append(f"cliché phrase: {phrase}")
    return found


def enforce(text: str) -> tuple[str, list[str]]:
    """Clean the auto-fixable tells, then report any that remain. Returns (clean_text, violations)."""
    cleaned = strip_footprints(text)
    return cleaned, scan_footprints(cleaned)
