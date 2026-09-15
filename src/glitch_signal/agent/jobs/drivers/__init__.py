"""Submission drivers — the only code in this repo that fills a form on an employer's site.

Each driver implements `submit.SubmissionDriver`: given a prepared package, drive the ATS's PUBLIC
application form and return evidence. They exist because neither Greenhouse nor Lever offers a
candidate-side API (both application POSTs require the EMPLOYER's key), so the public form is the
only route a candidate has.

Hard rules, enforced in `browser.py` and asserted by tests:
  - **Never create an account and never type a password.** Those stay operator actions.
  - **Never attempt a CAPTCHA.** On encountering one, stop and report `blocked_captcha`.
  - **Never invent a field value.** Everything submitted comes from the prepared package, which was
    itself built from the operator's approved answers. An unknown required field is a hard stop.
  - **Dry-run by default.** The final click is behind an explicit flag AND the policy gate.
"""
from __future__ import annotations

from glitch_signal.agent.jobs.drivers.greenhouse import GreenhouseDriver
from glitch_signal.agent.jobs.drivers.lever import LeverDriver

DRIVERS = {"greenhouse": GreenhouseDriver, "lever": LeverDriver}


def for_ats(ats: str):
    return DRIVERS.get((ats or "").lower())
