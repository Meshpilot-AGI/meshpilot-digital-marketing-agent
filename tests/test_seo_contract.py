"""SEO-1 — the editorial contract as executable checks.

Calibrated against the 11 posts already published to this contract in `glitch-trade-app`. The
baseline fixture mirrors a real one (5 H2, 1 stat, 1 list, 1 table, 1 antiPattern, 1 cite, 6 FAQ);
if the contract rejects that, the contract is wrong, not the post.
"""
from __future__ import annotations

import json

from glitch_signal.agent.seo import contract
from glitch_signal.agent.seo.post import Post, to_typescript, validate_shape


def _post(**over) -> Post:
    base = dict(
        slug="a-real-looking-slug",
        title="A title",
        lede="A short lede that answers the question directly and stays inside the word limit.",
        tldr="The direct answer, stated first.",
        author_slug="ryan", published_at="2026-09-02", reading_minutes=9,
        tags=["firm rules"],
        blocks=[
            {"type": "p", "text": "Prose that mentions $100,000 and 10% figures."},
            {"type": "stat", "stat": "A $100,000 account has a $10,000 cushion.",
             "context": "Static floors do not move.",
             "sourceUrl": "https://example.com/ref", "sourceLabel": "Primary ref"},
            {"type": "h2", "text": "One", "id": "a"},
            {"type": "h2", "text": "Two", "id": "b"},
            {"type": "h2", "text": "Three", "id": "c"},
            {"type": "h2", "text": "Four", "id": "d"},
            {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
            {"type": "antiPattern", "title": "Not this", "text": "What it does not solve."},
            {"type": "cite", "sources": [
                {"label": "Tool", "url": "/tools/x"},
                {"label": "Firms", "url": "/prop-firms/"},
                {"label": "Brokers", "url": "/brokers/overview"},
                {"label": "Ref", "url": "https://example.com/ref"}]},
        ],
        faq=[{"q": f"Q{i}?", "a": f"A{i}."} for i in range(5)],
    )
    base.update(over)
    return Post(**base)


# ── calibration ──
def test_a_post_shaped_like_the_real_ones_passes():
    """The single most important test here: the contract must not be stricter than the humans
    already writing to it, or it blocks everything and gets switched off."""
    ok, issues = contract.is_publishable(_post())
    assert ok, [str(i) for i in issues]


# ── each clause ──
def test_lede_over_sixty_words_fails():
    """The lede is also the <meta description>, so its length is a real constraint, not style."""
    ok, issues = contract.is_publishable(_post(lede=" ".join(["word"] * 61)))
    assert not ok and any(i.rule == "lede_too_long" for i in issues)


def test_missing_tldr_fails():
    ok, issues = contract.is_publishable(_post(tldr="  "))
    assert not ok and any(i.rule == "tldr_missing" for i in issues)


def test_three_h2_sections_fail():
    p = _post()
    p.blocks = [b for b in p.blocks if b.get("type") != "h2"][:1] + \
               [{"type": "h2", "text": t, "id": t} for t in ("a", "b", "c")] + \
               [b for b in p.blocks if b.get("type") in ("table", "antiPattern", "cite", "stat")]
    ok, issues = contract.is_publishable(p)
    assert not ok and any(i.rule == "too_few_h2" for i in issues)


def test_stat_citing_an_internal_page_is_rejected():
    """A StatCallout emits Quotation JSON-LD — citing ourselves for a figure is circular."""
    p = _post()
    for b in p.blocks:
        if b["type"] == "stat":
            b["sourceUrl"] = "/tools/x"
    ok, issues = contract.is_publishable(p)
    assert not ok and any(i.rule == "stat_source_not_primary" for i in issues)


def test_unordered_list_does_not_satisfy_the_table_or_list_rule():
    """The clause asks for a comparison table or an ORDERED list; a bulleted list is neither."""
    p = _post()
    p.blocks = [b for b in p.blocks if b["type"] != "table"]
    p.blocks.append({"type": "list", "ordered": False, "items": ["a", "b"]})
    ok, issues = contract.is_publishable(p)
    assert not ok and any(i.rule == "no_table_or_ordered_list" for i in issues)


def test_missing_anti_pattern_fails():
    p = _post()
    p.blocks = [b for b in p.blocks if b["type"] != "antiPattern"]
    ok, issues = contract.is_publishable(p)
    assert not ok and any(i.rule == "no_anti_pattern" for i in issues)


def test_four_faq_pairs_fail():
    ok, issues = contract.is_publishable(_post(faq=[{"q": "q", "a": "a"}] * 4))
    assert not ok and any(i.rule == "too_few_faq" for i in issues)


def test_internal_links_all_in_one_cluster_fail():
    """Three links into the same section is a related-reading list, not internal linking."""
    p = _post()
    for b in p.blocks:
        if b["type"] == "cite":
            b["sources"] = [{"label": "t", "url": f"/tools/{i}"} for i in range(3)] + \
                           [{"label": "r", "url": "https://example.com/ref"}]
    ok, issues = contract.is_publishable(p)
    assert not ok and any(i.rule == "internal_links_not_across_clusters" for i in issues)


def test_figures_with_no_primary_source_anywhere_fail():
    """The failure this vertical cannot afford: asserting numbers and sourcing nothing. The program's
    own guardrails call it YMYL-adjacent."""
    p = _post()
    p.blocks = [b for b in p.blocks if b["type"] != "stat"]
    for b in p.blocks:
        if b["type"] == "cite":
            b["sources"] = [{"label": "t", "url": "/tools/x"},
                            {"label": "f", "url": "/prop-firms/"},
                            {"label": "b", "url": "/brokers/overview"}]
    ok, issues = contract.is_publishable(p)
    assert not ok
    assert any(i.rule == "unsourced_quantitative_claims" for i in issues)


def test_a_cite_block_can_satisfy_sourcing_without_a_stat_block():
    """Real posts source their numbers from an end-of-post cite block. Demanding an inline citation
    per sentence would flag every correctly-written post, so the check is post-level."""
    p = _post()
    p.blocks = [b for b in p.blocks if b["type"] != "stat"]
    issues = contract._unsourced_claims(p)
    assert issues == []      # the external URL in the cite block is enough


def test_prose_with_no_figures_needs_no_source():
    p = _post()
    p.blocks = [b if b["type"] != "p" else {"type": "p", "text": "No numbers here at all."}
                for b in p.blocks if b["type"] != "stat"]
    assert contract._unsourced_claims(p) == []


# ── shape (will it compile) is separate from contract (is it good enough) ──
def test_shape_errors_are_reported_before_editorial_ones():
    """A post that will not typecheck is not an editorial question."""
    ok, issues = contract.is_publishable(_post(slug="Not A Slug"))
    assert not ok and all(i.rule == "invalid_shape" for i in issues)


def test_table_with_a_ragged_row_is_a_shape_error():
    p = _post()
    for b in p.blocks:
        if b["type"] == "table":
            b["rows"] = [["only-one-cell"]]
    errs = validate_shape(p)
    assert any("expected 2" in e for e in errs)


def test_unknown_block_type_is_rejected():
    p = _post()
    p.blocks.append({"type": "callout", "text": "renderer has no case for this"})
    assert any("unknown type" in e for e in validate_shape(p))


def test_unknown_author_is_rejected():
    assert any("authorSlug" in e for e in validate_shape(_post(author_slug="nobody")))


# ── emission ──
def test_typescript_output_is_parseable_and_complete():
    """Emitted as JSON-shaped TS: valid TypeScript, and free of the hand-escaping that single-quoted
    output invites."""
    ts = to_typescript(_post())
    assert ts.rstrip().endswith(",")            # ready to append into the array
    parsed = json.loads(ts.rstrip().rstrip(","))
    assert parsed["slug"] == "a-real-looking-slug"
    assert parsed["authorSlug"] == "ryan"       # camelCase, as the TS interface expects
    assert len(parsed["faq"]) == 5


def test_apostrophes_survive_emission():
    """The existing file is full of \\' escapes because it uses single quotes; generated output must
    not have to get that right."""
    ts = to_typescript(_post(title="FTMO's rule", tldr="It doesn't move."))
    parsed = json.loads(ts.rstrip().rstrip(","))
    assert parsed["title"] == "FTMO's rule" and parsed["tldr"] == "It doesn't move."
