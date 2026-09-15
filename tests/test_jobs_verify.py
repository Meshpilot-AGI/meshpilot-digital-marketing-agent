"""JOBS-4 acceptance — verify_cv_facts must FAIL CLOSED.

The lane's acceptance criterion (design § 10): a generated CV carrying a planted unsupported metric
is REJECTED. These tests are the proof.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs.verify import verify

FACTS = """
# CV -- Tejas Karan Agrawal
Performance marketer with 6+ years. Led a team running a ~$30K/day ad account for Udemy.
Four Shopify stores generating 2cr+ (~CAD $325K+) at a 15-20% net margin.
Operate a live store at 50.7K sessions, 1,559 orders.
Managed ~60-70L (~CAD $100K+) in Meta/TikTok ad spend at ~3x blended ROAS.
Quickads. IndoFolk Wellness. CableCommunity. Digistreet Infocom. Urban Classics Store.
Glitch Executor. Mesh Pilot. York University. George Brown College.
"""


# --- THE acceptance criterion ---------------------------------------------------------

def test_planted_unsupported_metric_is_rejected():
    doc = "Led a team running a ~$80K/day ad account for Udemy."
    r = verify(doc, FACTS)
    assert not r.ok
    assert any("80" in f.value for f in r.findings)


def test_inflated_years_are_rejected():
    r = verify("Performance marketer with 12+ years of experience.", FACTS)
    assert not r.ok
    assert any(f.value.startswith("12") for f in r.findings)


def test_invented_employer_is_rejected():
    """Fabricating a company reads as perfectly fluent — it must be caught structurally.

    (Note: "Shopify" is NOT a valid test subject here — it legitimately appears in the fact base as
    "four Shopify stores". Using it was my own error, and the verifier was right to pass it.)
    """
    r = verify("Performance Marketing Lead at Hootsuite and Quickads.", FACTS)
    assert not r.ok
    assert any("Hootsuite" in f.value for f in r.findings)


def test_a_company_the_operator_really_worked_with_is_not_flagged():
    """Shopify is in the fact base. Flagging it would be a false positive."""
    assert verify("Scaled four Shopify stores.", FACTS).ok


def test_supported_document_passes():
    doc = ("Performance marketer with 6+ years. Led a ~$30K/day account for Udemy at Quickads. "
           "Held a 15-20% net margin across four stores.")
    r = verify(doc, FACTS)
    assert r.ok, r.reasons()


def test_reordering_and_reframing_passes():
    """Tailoring is reorder/reframe/emphasise. That must NOT trip the verifier."""
    doc = ("Owned the full growth loop: 3x blended ROAS on Meta and TikTok spend, "
           "1,559 orders through a live store, and a 15-20% net margin sustained.")
    r = verify(doc, FACTS)
    assert r.ok, r.reasons()


# --- fail-closed semantics ------------------------------------------------------------

def test_empty_fact_base_fails_rather_than_passes():
    """With nothing to check against, NOTHING is supported. Vacuous truth is the dangerous default."""
    r = verify("Anything at all, 99 things.", "")
    assert not r.ok


def test_empty_document_fails():
    assert not verify("", FACTS).ok


def test_whitespace_only_document_fails():
    assert not verify("   \n\t ", FACTS).ok


# --- number normalization -------------------------------------------------------------

@pytest.mark.parametrize("written", ["1,559", "1559"])
def test_thousands_separators_compare_equal(written):
    assert verify(f"Delivered {written} orders.", FACTS).ok


def test_decimal_noise_compares_equal():
    assert verify("50.7K sessions.", FACTS).ok


def test_small_ordinals_are_not_treated_as_claims():
    """'across 3 channels' is prose, not a metric claim."""
    assert verify("Ran campaigns across 3 channels and 2 markets.", FACTS).ok


def test_a_large_unsupported_number_is_still_caught_even_near_supported_ones():
    r = verify("6+ years, $30K/day, and 4,200 enterprise clients.", FACTS)
    assert not r.ok
    assert any("4200" in f.value for f in r.findings)


# --- reporting ------------------------------------------------------------------------

def test_findings_carry_context_for_the_operator():
    r = verify("Scaled to 999K monthly sessions.", FACTS)
    assert not r.ok
    assert r.reasons() and "999" in r.reasons()[0]


def test_extra_allowed_lets_the_job_posting_supply_its_own_nouns():
    """A tailored CV names the target company. That noun comes from the JD, not the fact base."""
    doc = "Applying to Wealthsimple as a growth marketer with 6+ years."
    assert not verify(doc, FACTS).ok
    assert verify(doc, FACTS, extra_allowed={"Wealthsimple"}).ok


# --- entity extraction: two bugs found by running it on a REAL tailored CV --------------

def test_bullet_initial_words_are_not_treated_as_company_names():
    """A CV is mostly bullets. "- Managed a $30K/day account" flagged 'Managed' as an invented
    company on a real tailored CV — the cry-wolf failure that gets a verifier switched off."""
    from glitch_signal.agent.jobs.verify import _entities

    names = _entities("- Managed a budget at Acme.\n* Scaled four stores.\n1. Delivered growth.")
    assert "Managed" not in names
    assert "Scaled" not in names
    assert "Delivered" not in names
    assert "Acme" in names


def test_heading_and_bold_leads_are_skipped():
    from glitch_signal.agent.jobs.verify import _entities

    names = _entities("## Work Experience\n**Led** the team at Quickads.")
    assert "Work" not in names and "Led" not in names
    assert "Quickads" in names


def test_sentence_final_company_is_still_caught():
    """`_CAP` had \\b anchors and was used with fullmatch, so a token ending in punctuation
    ("Corp.", "Udemy.") never matched — silently exempting any company that ended a sentence."""
    from glitch_signal.agent.jobs.verify import _entities

    names = _entities("Ran the account at Nexolytics Corp.\nDrove spend for Udemy.")
    assert "Corp" in names and "Nexolytics" in names and "Udemy" in names


def test_a_sentence_final_invented_company_is_rejected_end_to_end():
    r = verify("Led paid media for Udemy at Nexolytics Corp.", FACTS)
    assert not r.ok
    assert any("Nexolytics" in f.value for f in r.findings)


# --- business vocabulary is not an "entity" (JOBS-14) -----------------------------------

def test_ordinary_business_vocabulary_is_not_flagged_as_an_invented_company():
    """A real CV rewrite that introduced "CRM" and "Team leadership" — both plainly reframings of
    experience already on the page — was REJECTED as containing unsupported entities. A verifier
    that blocks honest prose is the cry-wolf failure that gets it switched off."""
    doc = ("Owns the full growth loop: acquisition, CRM and post-purchase lifecycle. "
           "Team leadership and stakeholder management across Client accounts.")
    r = verify(doc, FACTS)
    assert r.ok, r.reasons()


def test_the_stopword_list_did_not_make_the_check_vacuous():
    """Adding generic vocabulary must not let a real employer or tool through."""
    r = verify("Led demand generation at Hootsuite using Braze and Marketo.", FACTS)
    assert not r.ok
    vals = " ".join(f.value for f in r.findings)
    assert "Hootsuite" in vals and "Braze" in vals and "Marketo" in vals


def test_no_employer_or_tool_name_leaked_into_the_stopwords():
    """Guard the guard: the list must stay generic. A company name here would silently exempt it."""
    from glitch_signal.agent.jobs.verify import _STOPWORDS

    for banned in ("Shopify", "Meta", "Google", "Udemy", "Quickads", "Braze", "Marketo",
                   "HubSpot", "Klaviyo", "TikTok", "Amazon", "Hootsuite"):
        assert banned not in _STOPWORDS, f"{banned} must never be a stopword"
