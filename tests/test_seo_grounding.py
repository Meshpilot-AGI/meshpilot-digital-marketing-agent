"""SEO-5 — the three gaps that let two real posts through (grounding, product claims, dead sources)."""
from __future__ import annotations

from glitch_signal.agent import firms
from glitch_signal.agent.seo import generate
from glitch_signal.agent.seo.post import Post


def _post(**kw) -> Post:
    base = dict(slug="s", title="t", lede="", tldr="", author_slug="ryan",
                published_at="2026-09-03", reading_minutes=8, blocks=[], faq=[])
    base.update(kw)
    return Post(**base)


# ── the distribution IS the fact ──
def _rows():
    return [
        {"firm_name": "FTMO", "rule_key": "min_profitable_days", "value_num": 0,
         "value_text": "0 minimum profitable days", "as_of": "2026-09-01"},
        {"firm_name": "Apex", "rule_key": "min_profitable_days", "value_num": 0,
         "value_text": "0 minimum profitable days", "as_of": "2026-09-01"},
        {"firm_name": "FundingPips", "rule_key": "min_profitable_days", "value_num": 7,
         "value_text": "7 minimum profitable days", "as_of": "2026-09-01"},
    ]


def test_a_firm_with_no_requirement_is_counted_not_dropped():
    """The zeros are the whole point. Counting only the quotable rows would have reported
    "1 of 1 firms have one" — grounding worse than silence."""
    block = firms.distribution_block(_rows(), ["min_profitable_days"])
    assert "1 of 3 firms have one." in block


def test_a_sentinel_zero_is_rendered_as_no_requirement_not_as_zero():
    """"0 minimum profitable days" is the phrasing that made these rows unpublishable in the first
    place — true as a number, misleading as a sentence."""
    block = firms.distribution_block(_rows(), ["min_profitable_days"])
    assert "FTMO: no requirement" in block
    assert "0 minimum profitable days" not in block


def test_the_block_forbids_the_exact_phrases_that_went_wrong():
    block = firms.distribution_block(_rows(), ["min_profitable_days"])
    assert "most firms" in block and "almost every" in block


def test_a_rule_topic_is_recognised_without_naming_a_firm():
    assert "min_profitable_days" in firms.rule_keys_for_topic(
        "Minimum trading days: why hitting your profit target early can still fail")


def test_an_unrelated_topic_asks_for_no_distribution():
    assert firms.rule_keys_for_topic("How to choose a VPS for algorithmic trading") == []


# ── invented consensus ──
def test_a_sweeping_claim_is_flagged_when_nothing_backs_it():
    """The sibling of `unsupported_figures`: that catches an invented number, this an invented
    consensus. The claim that shipped carried no digits, so nothing looked at it."""
    p = _post(blocks=[{"type": "p", "text": "Almost every challenge pairs a target with a day count."}])
    assert generate.unsupported_generalisations(p, "") == ["almost every"]


def test_the_same_claim_passes_once_a_distribution_was_supplied():
    """With counts in hand the model has what it needs, and the counts are there to quote."""
    p = _post(blocks=[{"type": "p", "text": "Most firms set one."}])
    assert generate.unsupported_generalisations(p, "min_profitable_days: 2 of 6 firms have one.") == []


def test_the_check_reads_the_lede_and_faq_too():
    """The claim that shipped was in the LEDE, which is also the meta description."""
    p = _post(lede="Most challenges require a minimum number of trading days.",
              faq=[{"q": "?", "a": "Nearly all firms do this."}])
    assert set(generate.unsupported_generalisations(p, "")) == {"most challenges", "nearly all"}


# ── claims about ourselves ──
_CAPS = ["blocks orders on daily-loss", "blocks orders on drawdown", "records each firm's rules"]


def test_an_undeclared_capability_is_flagged():
    """Nothing else can catch this: figure-grounding checks numbers, the contract checks structure,
    and no external source can confirm what our own code does."""
    p = _post(blocks=[{"type": "p", "text": "Glitch Executor treats a weekend cutoff as a "
                                            "pre-trade condition and blocks the order."}])
    out = generate.unverified_product_claims(p, brand_terms=["Glitch Executor"], capabilities=_CAPS)
    assert len(out) == 1 and "weekend cutoff" in out[0]


def test_a_declared_capability_passes():
    p = _post(blocks=[{"type": "p", "text": "Glitch Executor blocks orders on daily-loss rules "
                                            "before they reach the broker."}])
    assert generate.unverified_product_claims(p, brand_terms=["Glitch Executor"],
                                              capabilities=_CAPS) == []


def test_a_sentence_that_never_mentions_us_is_not_our_claim():
    p = _post(blocks=[{"type": "p", "text": "Some firms enforce a weekend cutoff automatically."}])
    assert generate.unverified_product_claims(p, brand_terms=["Glitch Executor"],
                                              capabilities=_CAPS) == []


def test_a_brand_that_declares_nothing_gets_no_check():
    """Stated rather than hidden: no declaration means no protection, not silent approval."""
    p = _post(blocks=[{"type": "p", "text": "Glitch Executor does anything you like."}])
    assert generate.unverified_product_claims(p, brand_terms=[], capabilities=[]) == []


# ── citations that do not resolve ──
async def test_a_404_source_is_rejected():
    """The contract required an external primary source and rejected a bare domain — it never
    checked the page exists. A shipped post cited a CFTC page that 404s: worse than no citation,
    because it looks like one."""
    p = _post(blocks=[{"type": "stat", "stat": "x", "context": "y",
                       "sourceUrl": "https://www.cftc.gov/gone.htm", "sourceLabel": "CFTC"}])

    async def fetch(url):
        return 404

    assert await generate.dead_sources(p, fetch) == ["https://www.cftc.gov/gone.htm -> HTTP 404"]


async def test_a_live_source_passes():
    p = _post(blocks=[{"type": "stat", "stat": "x", "context": "y",
                       "sourceUrl": "https://www.bis.org/publ/qtrpdf/r_qt1503h.htm", "sourceLabel": "BIS"}])

    async def fetch(url):
        return 200

    assert await generate.dead_sources(p, fetch) == []


async def test_a_network_blip_does_not_condemn_a_source():
    """An unreachable check is not evidence the page is gone — failing closed here would block
    publishing every time the network hiccups."""
    p = _post(blocks=[{"type": "stat", "stat": "x", "context": "y",
                       "sourceUrl": "https://example.org/a", "sourceLabel": "L"}])

    async def fetch(url):
        raise TimeoutError("blip")

    assert await generate.dead_sources(p, fetch) == []


async def test_author_does_not_touch_the_network_unless_asked():
    """A default that silently makes network calls turns every unit test into an integration test."""
    import inspect

    assert inspect.signature(generate.author).parameters["check_sources"].default is False


def test_a_negated_generalisation_is_the_post_getting_it_right():
    """"It's a firm-by-firm decision, not an industry standard" is the claim we WANT. Flagging it
    would spend a repair round making a correct sentence worse — and a check that cries wolf on
    correct writing gets ignored."""
    p = _post(blocks=[{"type": "p", "text": "It's a firm-by-firm decision, not an industry standard."}])
    assert generate.unsupported_generalisations(p, "") == []


def test_the_negation_window_does_not_swallow_a_real_claim():
    """A wide negation window would start excusing the claims this exists to catch."""
    p = _post(blocks=[{"type": "p", "text": "This is not a small point. Most firms require one."}])
    assert generate.unsupported_generalisations(p, "") == ["most firms"]


# ── the declared list, as shipped ──
def _shipped_caps():
    """Read the capabilities GE actually ships with, from the launchd job that runs the cycle."""
    import pathlib
    import plistlib

    d = plistlib.loads(pathlib.Path("deploy/com.meshpilot.seo-cycle.plist").read_bytes())
    env = d["EnvironmentVariables"]
    return ([t.strip() for t in env["GE_SEO_BRAND_TERMS"].split(",") if t.strip()],
            [c.strip() for c in env["GE_SEO_CAPABILITIES"].split(",") if c.strip()])


def test_the_shipped_list_rejects_the_claim_that_started_this():
    terms, caps = _shipped_caps()
    p = _post(blocks=[{"type": "p", "text":
        "Glitch Executor's engine treats a weekend cutoff as a pre-trade and pre-close condition "
        "and can block a new order before it reaches the broker."}])
    assert generate.unverified_product_claims(p, brand_terms=terms, capabilities=caps)


def test_order_routing_is_claimable_because_it_is_built():
    """Operator, 2026-09-03: routing and the pre-broker block ARE working — they sit behind a
    PRE-LAUNCH off-switch (`TRADE_EXEC_BROKER_ROUTING_ENABLED`, `TRADE_EXEC_DEMO_ONLY`).

    A held switch is a product decision, not a missing capability, and the earlier version of this
    test had it backwards: it read a disabled flag as an absent feature. That distinction is the
    whole point of the next test — a switched-off capability and a capability with no code path are
    different things, and only the second is a false claim."""
    terms, caps = _shipped_caps()
    for text in ("Glitch Executor routes your orders straight through to your broker.",
                 "Glitch Executor blocks an order before it reaches the broker when a rule would "
                 "be breached."):
        assert generate.unverified_product_claims(
            _post(blocks=[{"type": "p", "text": text}]),
            brand_terms=terms, capabilities=caps) == [], text


def test_the_shipped_list_rejects_the_news_blackout_claim():
    """NOT the same case as order routing, and the difference is the one that matters.

    Routing is built and held behind a flag. `block_minutes_around_news` — like `hold_over_weekend` —
    is stored per firm, served to the UI, and has NO code path: no rule of that name is emitted
    anywhere in `api/src/glitch_trade_api/execution/`. A flag you could flip is a decision; a rule
    that does not exist is a false claim."""
    terms, caps = _shipped_caps()
    p = _post(blocks=[{"type": "p", "text":
        "Glitch Executor enforces a news blackout window around high-impact releases."}])
    assert generate.unverified_product_claims(p, brand_terms=terms, capabilities=caps)


def test_the_shipped_list_permits_what_the_product_really_does():
    terms, caps = _shipped_caps()
    for text in ("Glitch Executor records each firm's published rules with a dated source.",
                 "Glitch Executor compares firms side by side on drawdown and daily loss.",
                 "Glitch Executor calculates drawdown against a firm's rules."):
        assert generate.unverified_product_claims(
            _post(blocks=[{"type": "p", "text": text}]), brand_terms=terms, capabilities=caps) == [], text


# ── matching a claim to a declared capability ──
def test_a_true_claim_in_different_words_still_matches():
    """Substring matching was the first attempt and flagged a TRUE claim: the declared "routes
    orders to your broker" did not match "routes your orders straight through to your broker".
    Padding the list with phrasings would have hidden the defect and grown a list nobody could
    maintain."""
    assert generate._capability_matches("routes orders to your broker",
                                        "glitch executor routes your orders straight through to "
                                        "your broker.")


def test_a_partial_overlap_is_not_a_match():
    """ALL content words, not a fraction — otherwise "enforces a weekend cutoff tied to the firm
    rule" slips past "records each firm's published rules" on the strength of sharing "firm"."""
    assert not generate._capability_matches(
        "records each firm's published rules",
        "glitch executor enforces a weekend cutoff tied to the firm rule.")


def test_filler_words_do_not_have_to_appear():
    assert generate._capability_matches("tracks account equity",
                                        "we track the equity on an account")  is False
    assert generate._capability_matches("trade journal", "glitch executor has a trade journal.")


def test_an_empty_capability_matches_nothing():
    assert not generate._capability_matches("the and of", "anything at all")


def test_your_platform_is_not_our_platform():
    """The declared term "our platform" matched inside "y-our platform", so a sentence about the
    READER's trading platform was read as a claim about ours. A check that fires on sentences it has
    no business reading gets switched off."""
    p = _post(blocks=[{"type": "p", "text":
        "The count is invisible from inside your platform."}])
    assert generate.unverified_product_claims(
        p, brand_terms=["our platform", "Glitch Executor"], capabilities=["trade journal"]) == []


def test_the_brand_is_still_matched_when_it_is_actually_named():
    p = _post(blocks=[{"type": "p", "text": "Our platform files your taxes."}])
    assert generate.unverified_product_claims(
        p, brand_terms=["our platform"], capabilities=["trade journal"])
