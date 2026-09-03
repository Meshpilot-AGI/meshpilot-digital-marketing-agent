"""The editorial contract, as executable checks (SEO-1).

The operator's AI-SEO program defines what a publishable post must contain. Every clause of it is
structural, which is the whole reason autonomous publishing is even arguable here: "is this good
enough to ship" becomes a set of pass/fail checks rather than a matter of taste.

From `glitch-trade-app/src/data/blog.ts`'s own editorial contract:

    - lede ≤ 60 words and contains the direct answer
    - ≥ 1 StatCallout with a primary-source URL
    - ≥ 4 H2 sections
    - one comparison table OR ordered list per post
    - one anti-pattern callout ("what this is not solving")
    - FAQ section with ≥ 5 Q&A pairs
    - ≥ 3 internal links across clusters
    - every quantitative claim cites a primary source

Calibrated against the 11 posts already published to it. A representative one carries 5 H2, 1 stat,
1 list, 1 table, 1 antiPattern, 1 cite and 6 FAQ pairs — comfortably inside every threshold, which
is what a contract should look like when the humans writing to it are doing so naturally.

**What these checks are not.** They verify structure, not truth. A post can satisfy every clause and
still be wrong, which is why the conscience critic and firm-rule grounding sit alongside them rather
than being replaced by them. Passing this contract earns a post the right to be *considered* for
publication, not the right to be believed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from glitch_signal.agent.seo.post import Post

LEDE_MAX_WORDS = 60
MIN_H2 = 4
MIN_FAQ = 5
MIN_INTERNAL_LINKS = 3
MIN_STATS = 1

# A quantitative claim in prose that carries no citation is the failure mode this vertical cannot
# afford: the program's own guardrails call it YMYL-adjacent and forbid "guaranteed pass" claims.
# Matches money, percentages and multiples — the shapes an unsourced number actually takes here.
_NUMBER_CLAIM = re.compile(r"(?<![\w/])(?:[$£€]\s?\d[\d,]*(?:\.\d+)?[kKmM]?|\d+(?:\.\d+)?\s?%)")


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.rule}: {self.detail}"


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _cluster(url: str) -> str:
    """The site section an internal link points at — `/tools/x` → `tools`."""
    return url.strip("/").split("/")[0] if url.startswith("/") else ""


def check(post: Post, *, min_clusters: int = 2) -> list[Violation]:
    """Every contract clause, as violations. Empty list means publishable *on structure*.

    `min_clusters` enforces the "across clusters" half of the internal-links rule: three links into
    the same section is a related-reading list, not the internal linking the program is asking for.
    """
    v: list[Violation] = []

    if _words(post.lede) > LEDE_MAX_WORDS:
        v.append(Violation("lede_too_long",
                           f"{_words(post.lede)} words, max {LEDE_MAX_WORDS} — it is also the "
                           f"<meta description>, so length is a real constraint"))
    if not post.lede.strip():
        v.append(Violation("lede_missing", "no lede"))
    if not post.tldr.strip():
        v.append(Violation("tldr_missing",
                           "no direct answer — this is the extraction zone AI search reads"))

    h2 = post.blocks_of("h2")
    if len(h2) < MIN_H2:
        v.append(Violation("too_few_h2", f"{len(h2)} H2 sections, need {MIN_H2}"))

    stats = post.blocks_of("stat")
    if len(stats) < MIN_STATS:
        v.append(Violation("no_stat_callout",
                           "needs a StatCallout with a primary-source URL (it emits Quotation JSON-LD)"))
    for i, s in enumerate(stats):
        url = str(s.get("sourceUrl") or "")
        if not url.startswith("http"):
            v.append(Violation("stat_source_not_primary",
                               f"stat {i} cites {url!r} — a StatCallout must cite an external "
                               f"primary source, not an internal page"))
        elif len(url.split("/", 3)) < 4 or not url.split("/", 3)[3].strip("/"):
            # The first generated post cited `https://apextraderfunding.com` — a homepage is where a
            # claim might live, not where it does. A citation has to point at the page that supports
            # the figure, or a reader cannot check it.
            v.append(Violation("stat_source_is_bare_domain",
                               f"stat {i} cites {url!r} — cite the specific page that supports the "
                               f"figure, not the site root"))

    if not (post.blocks_of("table") or [b for b in post.blocks_of("list") if b.get("ordered")]):
        v.append(Violation("no_table_or_ordered_list",
                           "needs one comparison table or ordered list"))

    if not post.blocks_of("antiPattern"):
        v.append(Violation("no_anti_pattern",
                           "needs an anti-pattern callout — what this is NOT solving"))

    if len(post.faq) < MIN_FAQ:
        v.append(Violation("too_few_faq",
                           f"{len(post.faq)} Q&A pairs, need {MIN_FAQ} (drives FAQPage JSON-LD)"))

    internal = post.internal_links()
    if len(internal) < MIN_INTERNAL_LINKS:
        v.append(Violation("too_few_internal_links",
                           f"{len(internal)} internal links, need {MIN_INTERNAL_LINKS}"))
    else:
        clusters = {c for c in (_cluster(u) for u in internal) if c}
        if len(clusters) < min_clusters:
            v.append(Violation("internal_links_not_across_clusters",
                               f"all internal links point into {sorted(clusters)} — the rule asks "
                               f"for links ACROSS clusters, not a related-reading list"))

    v += _unsourced_claims(post)
    return v


def _unsourced_claims(post: Post) -> list[Violation]:
    """Quantitative claims in prose with no citation anywhere in the post.

    Deliberately post-level rather than sentence-level: a `cite` block at the end is how these posts
    actually source their numbers, so demanding an inline citation per sentence would flag every
    correctly-written post. This catches the real failure — a post that asserts figures and sources
    nothing at all.
    """
    prose = " ".join(str(b.get("text") or "") for b in post.blocks
                     if b.get("type") in ("p", "h2", "h3"))
    numbers = _NUMBER_CLAIM.findall(prose)
    if not numbers:
        return []
    has_source = bool(post.stat_sources() or [u for u in post.cite_urls() if u.startswith("http")])
    if has_source:
        return []
    return [Violation("unsourced_quantitative_claims",
                      f"prose asserts figures ({', '.join(numbers[:4])}"
                      f"{'…' if len(numbers) > 4 else ''}) but the post cites no primary source")]


def is_publishable(post: Post) -> tuple[bool, list[Violation]]:
    """Structural gate. Shape errors are reported first — a post that will not compile is not an
    editorial question."""
    from glitch_signal.agent.seo.post import validate_shape

    shape = [Violation("invalid_shape", e) for e in validate_shape(post)]
    if shape:
        return False, shape
    issues = check(post)
    return (not issues), issues
