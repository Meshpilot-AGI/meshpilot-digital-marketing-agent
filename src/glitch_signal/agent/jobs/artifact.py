"""Materialize the APPROVED CV into a file the submitter can upload.

The operator approves a document, not an intention. `job_application.tailored_cv_md` holds the exact
markdown shown on the Discord card; this module turns that — and only that — into the PDF that gets
uploaded. It never tailors, never edits, never falls back to the master CV: the whole point is that
the bytes going to the employer descend from the bytes the operator saw.

Rendering happens at submit time rather than at approval time because the PDF has nowhere durable to
live. `render_cv_pdf` writes to local disk, and every process here is ephemeral — FastAPI Cloud
replaces containers on deploy, and the submitter is a poll loop on Railway. Markdown in the database
plus a deterministic render is the version that survives a restart.
"""
from __future__ import annotations

import pathlib
from typing import Any

import structlog

log = structlog.get_logger()


class UnverifiedCvError(RuntimeError):
    """The stored markdown no longer verifies against the fact base."""


def ensure_cv_file(application: dict, cv_text: str, *, out_dir: str | None = None) -> str:
    """Return a path to the approved CV as a PDF, rendering it if needed.

    Re-verifies before rendering. That looks redundant — the markdown was verified before the card
    was posted — but the fact base is editable and the row is long-lived, so a claim that was
    supported at approval time may not be supported now. The check is cheap and the failure mode it
    guards against (sending an unsupported claim to an employer under the operator's name) is not
    recoverable, so it runs every time rather than being trusted from history.
    """
    from glitch_signal.agent.jobs import verify as _verify
    from glitch_signal.agent.jobs.render import render_cv_pdf

    existing = application.get("tailored_cv_path")
    if existing and pathlib.Path(existing).exists():
        return str(existing)

    md = (application.get("tailored_cv_md") or "").strip()
    if not md:
        # Not an error the caller should paper over: without the approved document there is nothing
        # legitimate to upload, and tailoring a replacement here would substitute an unapproved one.
        raise FileNotFoundError(
            "no approved CV stored on this application (tailored_cv_md is empty) — it must be "
            "re-tailored and re-approved before it can be submitted")

    result = _verify.verify(md, cv_text)
    if not result.ok:
        raise UnverifiedCvError(
            "the approved CV no longer verifies against the fact base: "
            + "; ".join(result.reasons()[:3]))

    out: Any = None
    if out_dir:
        out = pathlib.Path(out_dir) / f"cv-{application.get('id')}.pdf"
    path = render_cv_pdf(md, out)
    log.info("jobs.artifact.rendered", application=str(application.get("id")), path=str(path))
    return str(path)
