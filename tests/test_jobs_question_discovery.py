"""JOBS-20 — the form's own required questions decide whether we may submit.

Measured on Later's real posting 2026-09-17: the worker passed the application row's own (empty)
answer keys as "the questions", so `resolve_answers` got an empty list, found nothing missing, and
`prepare()` returned ready. The form's two required questions were never seen. Live, that submits an
application with both blank — worse than not applying, because it burns the req.
"""
from __future__ import annotations

from glitch_signal.agent.jobs.drivers import browser as bx
from glitch_signal.agent.jobs.drivers.greenhouse import GreenhouseDriver

IDENTITY = {"first_name": "Tejas", "last_name": "Karan Agrawal", "email": "t@example.com",
            "phone": "+1-437", "city": "Toronto, ON", "country": "Canada",
            "linkedin": "https://linkedin.com/in/tejas-karan-agrawal",
            "portfolio": "https://tejaskaranagrawal.com"}
BANK = {"what are your salary expectations for this role": "$120,000 – $140,000 CAD"}


def _d(bank=None):
    return GreenhouseDriver(identity=IDENTITY, live=False, bank=bank if bank is not None else BANK)


def test_a_custom_linkedin_question_resolves_from_identity():
    """On Later's form LinkedIn is `question_37726385002` with NO name attribute — a selector built
    from `name*='linkedin'` matches nothing, and the field is REQUIRED. Label matching is the only
    durable handle, and the value comes from the brand config, never invented."""
    assert _d()._resolve("LinkedIn Profile*") == IDENTITY["linkedin"]


def test_a_banked_question_resolves_by_exact_normalised_label():
    assert _d()._resolve("What are your salary expectations for this role?*").startswith("$120,000")


def test_an_unbanked_essay_resolves_to_nothing():
    """Decision 4: the agent never composes a free-text answer. Returning None is what routes the
    whole application to the operator."""
    assert _d()._resolve("Why do you go to work? What motivates you?*") is None


def test_a_near_match_is_a_miss_not_a_guess():
    """"salary expectations" vs "salary expectations for this role" are different strings. A
    confident near-match is exactly how a wrong answer gets submitted under someone's name."""
    assert _d()._resolve("What are your salary expectations?*") is None


def test_only_genuinely_semantic_fields_are_excluded_from_the_questions():
    """These have real semantic inputs (#first_name, input[type=email], …), so asking the bank about
    them would report every application as manual_required.

    Location is deliberately NOT here: DEPT renders it as a custom question, and excluding it meant
    a required field went unfilled and unnoticed."""
    for label in ("First Name*", "Email*", "Phone*", "Country*"):
        assert bx.label_key(label) in bx.CORE_LABELS
    for label in ("Location (City)*", "Where are you currently located?*", "LinkedIn Profile*"):
        assert bx.label_key(label) not in bx.CORE_LABELS


def test_label_key_normalises_the_required_marker_and_punctuation():
    assert bx.label_key("  What are your   salary expectations?* ") == "what are your salary expectations"
    assert bx.label_key("LinkedIn Profile*") == "linkedin profile"


async def test_required_questions_drops_the_fields_we_fill_ourselves():
    class _Page:
        async def evaluate(self, _js):
            return [{"label": "First Name*", "id": "first_name", "tag": "input", "type": "text"},
                    {"label": "LinkedIn Profile*", "id": "question_1", "tag": "input", "type": "text"},
                    {"label": "Why do you go to work?*", "id": "question_2", "tag": "textarea", "type": ""}]

    got = [q["label"] for q in await bx.required_questions(_Page())]
    assert got == ["LinkedIn Profile*", "Why do you go to work?*"]


def test_a_location_question_resolves_rather_than_being_skipped():
    """⚠️ DEPT renders "Where are you currently located?*" as a CUSTOM question with no semantic
    input. It was in CORE_LABELS, so it was neither filled by selector nor offered to the resolver —
    a REQUIRED field left silently blank in a rehearsal that otherwise looked clean (2026-09-17).

    Anything an employer might render as a custom question belongs in the resolver. Being asked
    twice is harmless; being skipped is not."""
    assert _d()._resolve("Where are you currently located?*") == IDENTITY["city"]
    assert _d()._resolve("Location (City)*") == IDENTITY["city"]
    assert _d()._resolve("What is the location where you permanently reside?*") == IDENTITY["city"]
    assert bx.label_key("where are you currently located") not in bx.CORE_LABELS
