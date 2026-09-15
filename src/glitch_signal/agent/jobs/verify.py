"""verify_cv_facts — the fail-closed gate between a generated document and the operator's name.

Design § 5. A tailored CV that invents a number is worse than no CV: it is a lie told in the
operator's name, to a hiring manager, at scale, and it is the operator who has to defend it in an
interview. So generation is not trusted — it is CHECKED, deterministically, and a document with an
unsupported claim never reaches an approval card.

What is checked, and why only these:

1. **Every quantity.** Numbers are the claims that get verified by employers and the ones a model
   most readily embellishes ("6 years" → "8 years", "$30K/day" → "$50K/day"). Each numeric token in
   the generated text must appear in the fact base, modulo formatting.
2. **Every employer and proper-noun-ish capitalised token.** Inventing a company you worked at is
   the most damaging possible fabrication, and unlike a number it reads as perfectly fluent.

What is deliberately NOT checked: prose, framing, ordering, emphasis, and word choice. Those are
exactly what tailoring is FOR — "keywords get reformulated, never fabricated".

The check is deliberately dumb and deterministic. An LLM judging whether a claim is "supported"
fails in the direction that matters: it rationalises. A regex cannot be talked into anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A number with optional currency/scale decoration: 30K, $30,000, ₹2cr, 3x, 15-20%, 6+, 50.7K
_NUM = re.compile(r"""
    (?P<num>
        \d[\d,.\s]*\d | \d
    )
    (?P<suffix>\s*(?:%|x|\+|k|m|b|cr|lakh|l)\b)?
""", re.I | re.X)

# A capitalised token is only treated as a NAME when it appears mid-sentence. A sentence-initial
# capital is ambiguous — "Held a 15-20% margin" and "Hootsuite raised a round" look identical — and
# flagging those makes the verifier cry wolf on ordinary prose. A verifier with false positives gets
# switched off, which is strictly worse than no verifier, so the ambiguity is resolved toward silence
# and the numeric check carries the load.
# A CV is mostly bullets and headings, where the first word of a line is capitalised by convention
# ("- Managed a $30K/day account"). Those positions are sentence-initial in every way that matters,
# so strip the line's leading furniture — markdown bullets, numbering, heading hashes, bold markers —
# and skip the first word after it. Missing this flagged "Managed" as an invented company on a real
# tailored CV, which is exactly the cry-wolf failure that gets a verifier switched off.
_LINE_LEAD = re.compile(r"^[\s>#*\-\u2022\u00b7]*(?:\d+[.)]\s*)?(?:\*\*)?", re.M)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?:])\s+")
# No \b anchors: this is used with fullmatch on an already-trimmed token, and a trailing "\b"
# refuses to match a token ending in punctuation ("Corp.", "Udemy.") — which silently exempted every
# company name that happened to end a sentence.
_CAP = re.compile(r"[A-Z][A-Za-z0-9&.\-]{2,}")
_TRIM = " \t,;:()[]{}\"'`*_!?."


def _candidate_names(text: str) -> set[str]:
    """Capitalised tokens that are NOT first in their line or sentence."""
    out: set[str] = set()
    for line in (text or "").splitlines():
        body = _LINE_LEAD.sub("", line, count=1)
        for si, sentence in enumerate(_SENTENCE_SPLIT.split(body)):
            words = sentence.split()
            # Skip the first word of every sentence, and of the line itself.
            for w in words[1:]:
                tok = w.strip(_TRIM)
                if tok and _CAP.fullmatch(tok):
                    out.add(tok.rstrip("."))
            _ = si
    return {w for w in out if w and w not in _STOPWORDS}


# Still excluded even mid-sentence: CV furniture and months, which are capitalised by convention.
_STOPWORDS = frozenset("""
January February March April May June July August September October November December
Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec
Summary Experience Education Skills Projects Certifications Present Current Remote Contact
CV Resume Profile Objective References Available Upon Request Achievements Highlights
""".split())


@dataclass
class Finding:
    kind: str          # "metric" | "entity"
    value: str
    context: str


@dataclass
class VerifyResult:
    ok: bool
    findings: list[Finding] = field(default_factory=list)

    def reasons(self) -> list[str]:
        return [f"unsupported {f.kind}: {f.value!r} (…{f.context}…)" for f in self.findings]


def _norm_num(raw: str) -> str:
    """Normalize a numeric token so 30,000 / 30000 / 30 000 compare equal, and 30.0 == 30."""
    s = re.sub(r"[,\s]", "", raw)
    if s.endswith("."):
        s = s[:-1]
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or raw


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM.finditer(text or ""):
        n = _norm_num(m.group("num"))
        if not n:
            continue
        out.add(n)
        suf = (m.group("suffix") or "").strip().lower()
        if suf:
            out.add(n + suf)
    return out


def _entities(text: str) -> set[str]:
    """Candidate NAMES in `text` — capitalised tokens that are not line- or sentence-initial."""
    return _candidate_names(text)


def _fact_base_names(text: str) -> set[str]:
    """Names KNOWN from the fact base. Here we take every capitalised token, sentence-initial
    included: over-collecting on the allowed side can only make the check more permissive, and a
    company that happens to start a line in the CV is still a company the operator worked at."""
    return {w.rstrip(".") for w in re.findall(r"\b([A-Z][A-Za-z0-9&.\-]{2,})\b", text or "")
            if w.rstrip(".") not in _STOPWORDS}


def _context(text: str, needle: str, width: int = 40) -> str:
    i = text.find(needle)
    if i == -1:
        return ""
    return re.sub(r"\s+", " ", text[max(0, i - width): i + len(needle) + width]).strip()


# Years are the one quantity a tailored CV may legitimately restate in a form the source doesn't
# literally contain (a date range in the source becoming "6 years" in prose). Small integers are
# also overwhelmingly ordinal noise ("3 channels"), not claims. Both are checked against the source
# ANYWAY — this list only prevents treating a bare digit as a fabricated metric.
_TRIVIAL = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"})


def verify(generated: str, fact_base: str, *, extra_allowed: set[str] | None = None) -> VerifyResult:
    """Check a generated document against the fact base. FAILS CLOSED.

    An empty fact base is a failure, not a pass: with nothing to check against, nothing is supported.
    """
    findings: list[Finding] = []
    if not (generated or "").strip():
        return VerifyResult(ok=False, findings=[Finding("metric", "<empty document>", "")])
    if not (fact_base or "").strip():
        return VerifyResult(ok=False, findings=[Finding("metric", "<empty fact base>", "")])

    allowed_nums = _numbers(fact_base)
    allowed_ents = _fact_base_names(fact_base) | {e for e in (extra_allowed or set())} \
        | {e.lower() for e in (extra_allowed or set())}

    for n in sorted(_numbers(generated)):
        if n in _TRIVIAL or n in allowed_nums:
            continue
        # A decorated form is supported if its bare number is (e.g. "30k" when the source says 30000
        # is NOT enough — but "$30K" when the source says "30K" is).
        bare = re.sub(r"[a-z%+x]+$", "", n)
        if bare and bare in allowed_nums and bare != n:
            continue
        findings.append(Finding("metric", n, _context(generated, n)))

    for e in sorted(_entities(generated)):
        if e in allowed_ents or e.lower() in allowed_ents:
            continue
        findings.append(Finding("entity", e, _context(generated, e)))

    return VerifyResult(ok=not findings, findings=findings)
