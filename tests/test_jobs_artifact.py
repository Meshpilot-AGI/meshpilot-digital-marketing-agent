"""JOBS-13 — the approved CV must be the one that gets uploaded."""
from __future__ import annotations

import pathlib

import pytest

from glitch_signal.agent.jobs import artifact

CV = "# Tejas Karan Agrawal\nGrew pipeline 30% at Example Co.\nBuilt the attribution stack."


def test_an_application_with_no_stored_cv_refuses_rather_than_substituting_one():
    """Tailoring a replacement here would upload a document the operator never saw. The first real
    approval (2026-09-16) hit exactly this state, because the CV was not persisted at the time."""
    with pytest.raises(FileNotFoundError, match="re-tailored and re-approved"):
        artifact.ensure_cv_file({"id": "a1", "tailored_cv_md": ""}, CV)


def test_a_cv_that_no_longer_verifies_is_refused(monkeypatch):
    """The fact base is editable and the row is long-lived, so a claim supported at approval time
    may not be supported now. Sending an unsupported claim to an employer is not recoverable."""
    app = {"id": "a1", "tailored_cv_md": "# CV\nGrew revenue 400% and ran a $50M budget."}
    with pytest.raises(artifact.UnverifiedCvError):
        artifact.ensure_cv_file(app, CV)


def test_an_existing_file_is_reused_not_re_rendered(tmp_path, monkeypatch):
    f = tmp_path / "cv.pdf"
    f.write_bytes(b"%PDF-1.4 existing")

    def boom(*a, **k):
        raise AssertionError("must not re-render when the artifact already exists")

    monkeypatch.setattr("glitch_signal.agent.jobs.render.render_cv_pdf", boom)
    assert artifact.ensure_cv_file({"id": "a", "tailored_cv_path": str(f)}, CV) == str(f)


def test_the_stored_markdown_is_what_gets_rendered(tmp_path, monkeypatch):
    seen = {}

    def fake_render(md, out=None):
        seen["md"] = md
        p = pathlib.Path(out) if out else tmp_path / "x.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4")
        return p

    monkeypatch.setattr("glitch_signal.agent.jobs.render.render_cv_pdf", fake_render)
    approved = "# Tejas Karan Agrawal\nBuilt the attribution stack."
    out = artifact.ensure_cv_file({"id": "a7", "tailored_cv_md": approved}, CV,
                                  out_dir=str(tmp_path))
    assert seen["md"] == approved, "the uploaded PDF must descend from the approved markdown"
    assert out.endswith("cv-a7.pdf")


def _worker():
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "submitter"))
    import worker
    return worker


def test_identity_splits_the_single_location_into_city_and_country():
    """⚠️ Measured against the real Flipp/DEPT/Later forms 2026-09-16: all three mark Country,
    Location (City) and LinkedIn Profile REQUIRED, and the driver knew none of them — a submission
    would have been rejected by the form's own validation with every mapped field correct."""
    i = _worker().identity_for({"contact": {
        "full_name": "Tejas Karan Agrawal", "email": "e@x.com", "phone": "+1-437",
        "location": "Toronto, ON, Canada", "linkedin": "https://linkedin.com/in/x"}})
    assert i["country"] == "Canada"
    assert i["city"] == "Toronto, ON"
    assert i["linkedin"].endswith("/x")
    assert i["first_name"] == "Tejas" and i["last_name"] == "Karan Agrawal"


def test_a_location_with_no_country_fails_visibly_rather_than_guessing():
    """A wrong split leaves a field the form rejects. Inferring "Canada" would put an unverified
    claim about the operator on someone else's form."""
    i = _worker().identity_for({"contact": {"full_name": "A B", "location": "Toronto"}})
    assert i["city"] == "Toronto" and i["country"] == ""
