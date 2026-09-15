"""JOBS-7 — the submission drivers and the submitter's gates.

Playwright is NOT installed in this environment (it lives only in the submitter image), so these
test the parts that must hold regardless of a browser: the hard stops, the confirmation heuristic,
and that the main package still imports without Playwright.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs.drivers import DRIVERS, for_ats
from glitch_signal.agent.jobs.drivers import browser as bx


def test_only_greenhouse_and_lever_have_drivers():
    """Workday and Ashby are deliberately out of scope — guessing at an unknown form is how a
    broken application gets sent."""
    assert sorted(DRIVERS) == ["greenhouse", "lever"]
    assert for_ats("workday") is None
    assert for_ats("ashby") is None


def test_the_main_package_imports_without_playwright():
    """Playwright is in the submitter image only. If importing a driver pulled it in, the API
    service would fail to boot."""
    import importlib

    for mod in ("glitch_signal.agent.jobs.drivers",
                "glitch_signal.agent.jobs.drivers.greenhouse",
                "glitch_signal.agent.jobs.drivers.lever"):
        importlib.import_module(mod)
    with pytest.raises(ImportError):
        importlib.import_module("playwright.async_api")


# --- hard stops -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_captcha_stops_the_run():
    """Defeating bot-detection is out of scope permanently, not merely unimplemented."""
    class Page:
        url = "https://x/y"

        def locator(self, sel):
            class L:
                async def count(_self):
                    return 1 if "recaptcha" in sel else 0
            return L()

    with pytest.raises(bx.BlockedByCaptchaError):
        await bx.assert_no_blockers(Page())


@pytest.mark.asyncio
async def test_a_password_field_stops_the_run():
    """The agent must never create an account or type a password."""
    class Page:
        url = "https://x/y"

        def locator(self, sel):
            class L:
                async def count(_self):
                    return 1 if "password" in sel else 0
            return L()

    with pytest.raises(bx.RequiresAccountError):
        await bx.assert_no_blockers(Page())


def test_no_captcha_solver_is_referenced_anywhere_in_the_drivers():
    import pathlib

    src = "\n".join(p.read_text() for p in
                    pathlib.Path("src/glitch_signal/agent/jobs").rglob("*.py")).lower()
    for banned in ("capsolver", "2captcha", "anticaptcha", "deathbycaptcha", "captcha_solver"):
        assert banned not in src


# --- confirmation must be EXPLICIT -----------------------------------------------------

@pytest.mark.parametrize("text", [
    "Thank you for applying!", "Your application has been submitted.",
    "We have received your application.", "Application received",
    "Thanks for your interest in this role",
])
def test_explicit_confirmations_are_recognized(text):
    assert bx.looks_submitted(text)


@pytest.mark.parametrize("text", [
    "", "Apply for this job", "Submit application", "An error occurred",
    "Please complete the required fields", "Loading…",
])
def test_a_page_that_merely_stopped_erroring_is_not_proof(text):
    """A false positive means the operator believes an application was sent when it was not."""
    assert not bx.looks_submitted(text)


# --- driver defaults -------------------------------------------------------------------

@pytest.mark.parametrize("cls_name", ["greenhouse", "lever"])
def test_drivers_default_to_not_sending(cls_name):
    """`live` defaults False: the final click needs an explicit opt-in."""
    cls = DRIVERS[cls_name]
    d = cls(identity={})
    assert d.live is False


def test_lever_apply_url_is_derived_not_guessed():
    from glitch_signal.agent.jobs.drivers.lever import apply_url

    assert apply_url("https://jobs.lever.co/acme/abc") == "https://jobs.lever.co/acme/abc/apply"
    assert apply_url("https://jobs.lever.co/acme/abc/") == "https://jobs.lever.co/acme/abc/apply"
    assert apply_url("https://jobs.lever.co/acme/abc/apply") == "https://jobs.lever.co/acme/abc/apply"


# --- the submitter's own switches ------------------------------------------------------

def test_submitter_defaults_to_dry_run(monkeypatch):
    """SUBMITTER_LIVE must be exactly 'true'. Anything else — unset, '1', 'yes' — is a dry run."""
    import importlib

    for val, expected in [(None, False), ("", False), ("1", False), ("yes", False),
                          ("True", True), ("true", True)]:
        if val is None:
            monkeypatch.delenv("SUBMITTER_LIVE", raising=False)
        else:
            monkeypatch.setenv("SUBMITTER_LIVE", val)
        import submitter.worker as w
        importlib.reload(w)
        assert w.LIVE is expected, f"SUBMITTER_LIVE={val!r} should give LIVE={expected}"


def test_submitter_asks_the_policy_gate_rather_than_its_own_counter():
    """The submitter must not be able to outrun a cap the rest of the system believes is in force."""
    import inspect

    import submitter.worker as w

    src = inspect.getsource(w.one_pass)
    assert 'policy.allow("job_apply"' in src
    assert "break" in src, "a blocked policy check must stop the pass, not just skip one row"


def test_identity_comes_from_config_never_inferred():
    import submitter.worker as w

    ident = w.identity_for({"contact": {"full_name": "Tejas Karan Agrawal",
                                        "email": "a@b.com", "phone": "+1"}})
    assert ident["first_name"] == "Tejas" and ident["last_name"] == "Karan Agrawal"
    assert w.identity_for({})["email"] == ""
