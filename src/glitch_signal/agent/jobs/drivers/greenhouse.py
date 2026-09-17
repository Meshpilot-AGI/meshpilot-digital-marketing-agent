"""Greenhouse public application form.

Greenhouse's application POST API needs the EMPLOYER's key, so a candidate must use the public form
at `job-boards.greenhouse.io/{board}/jobs/{id}`. Field names there are stable and semantic
(`first_name`, `last_name`, `email`, `phone`, a resume file input), which is why Greenhouse is one
of the two in-scope ATSes.
"""
from __future__ import annotations

from typing import Any

import structlog

from glitch_signal.agent.jobs.drivers import browser as bx

log = structlog.get_logger()

# ⚠️ Measured against three REAL Flipp/DEPT/Later forms on 2026-09-16, not assumed. The first four
# were all this driver knew, and every one of those forms also marks Country, Location (City) and
# LinkedIn Profile REQUIRED — so a submission would have been rejected by the form's own validation
# with every mapped field filled correctly. The selectors below are the ones those pages actually
# expose; `auto_fill_country` etc. are Greenhouse's own ids for its combobox fields.
_FIELDS = {
    "first_name": ["input#first_name", "input[name='first_name']", "input[autocomplete='given-name']"],
    "last_name": ["input#last_name", "input[name='last_name']", "input[autocomplete='family-name']"],
    "email": ["input#email", "input[name='email']", "input[type='email']"],
    "phone": ["input#phone", "input[name='phone']", "input[type='tel']"],
    "city": ["input#auto_fill_location", "input[name*='location']", "input[id*='location']"],
    "country": ["input#auto_fill_country", "input[name*='country']", "input[id*='country']"],
    "linkedin": ["input[name*='linkedin' i]", "input[id*='linkedin' i]"],
}
_RESUME = ["input[type='file'][name*='resume']", "input#resume", "input[type='file']"]
_SUBMIT = ["button#submit_app", "button[type='submit']", "input[type='submit']"]


async def _fill_first(page: Any, selectors: list[str], value: str) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        if await loc.count():
            await loc.fill(value)
            return True
    return False


class GreenhouseDriver:
    """Implements `submit.SubmissionDriver`."""

    def __init__(self, *, identity: dict, live: bool = False, screenshot_dir: str | None = None):
        # `live=False` means: do everything EXCEPT the final click. The default is not-sending.
        self.identity = identity
        self.live = live
        self.screenshot_dir = screenshot_dir

    async def submit(self, package: dict) -> dict:
        from playwright.async_api import async_playwright

        url = package["url"]
        async with async_playwright() as pw:
            browser_, ctx, page = await bx.new_page(pw)
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await bx.assert_no_blockers(page)

                missing, filled = [], {}
                for key, sels in _FIELDS.items():
                    val = self.identity.get(key)
                    if not val:
                        missing.append(f"{key} (no value in the brand config)")
                        continue
                    if await _fill_first(page, sels, str(val)):
                        filled[key] = str(val)
                    else:
                        missing.append(f"{key} (no matching input on the form)")

                uploaded = False
                for sel in _RESUME:
                    loc = page.locator(sel).first
                    if await loc.count():
                        await loc.set_input_files(package["cv_path"])
                        uploaded = True
                        break
                if not uploaded:
                    return {"ok": False, "failure_reason": "no resume file input found on the form",
                            "evidence": await bx.evidence_from(page)}

                # Answers were resolved from the operator's bank BEFORE we got here. We only place
                # them; we never compose one, and an unplaceable answer is a hard stop rather than a
                # silently skipped question.
                unplaced = []
                for question, answer in (package.get("answers") or {}).items():
                    if not await _place_answer(page, question, str(answer)):
                        unplaced.append(question)
                if unplaced:
                    return {"ok": False,
                            "failure_reason": f"could not place approved answers: {unplaced[:3]}",
                            "evidence": await bx.evidence_from(page)}

                shot = f"{self.screenshot_dir}/gh-{package.get('application_id')}.png" if self.screenshot_dir else None
                if not self.live:
                    ev = await bx.evidence_from(page, shot)
                    # ⚠️ WHAT was filled, not merely that filling did not raise. The first rehearsal
                    # recorded only "form filled, NOT submitted" plus the page's body text — which is
                    # mostly the job description, and proves nothing about the fields. A rehearsal
                    # whose whole purpose is "show me what would be sent" has to say what would be
                    # sent, or the operator is trusting the same untested path they wanted rehearsed.
                    ev.update({"dry_run": True,
                               "fields_filled": filled,
                               "fields_missing": missing,
                               "resume_uploaded": uploaded,
                               "answers_placed": dict(package.get("answers") or {})})
                    return {"ok": False, "failure_reason": "dry run — form filled, NOT submitted",
                            "evidence": ev}

                clicked = False
                for sel in _SUBMIT:
                    loc = page.locator(sel).first
                    if await loc.count():
                        await loc.click()
                        clicked = True
                        break
                if not clicked:
                    return {"ok": False, "failure_reason": "no submit button found",
                            "evidence": await bx.evidence_from(page, shot)}

                await page.wait_for_load_state("networkidle", timeout=bx.NAV_TIMEOUT_MS)
                ev = await bx.evidence_from(page, shot)
                ok = bx.looks_submitted(ev.get("confirmation_text", ""))
                return {"ok": ok, "evidence": ev,
                        "failure_reason": None if ok else "no confirmation text after submit",
                        "fields_missing": missing}
            except (bx.BlockedByCaptchaError, bx.RequiresAccountError) as exc:
                return {"ok": False, "failure_reason": str(exc), "evidence": {"url": page.url}}
            finally:
                await ctx.close()
                await browser_.close()


async def _place_answer(page: Any, question: str, answer: str) -> bool:
    """Find the control whose LABEL matches the question and set it. Label-based, never positional:
    a positional guess silently answers the wrong question."""
    label = page.get_by_label(question, exact=False)
    if await label.count():
        target = label.first
        tag = await target.evaluate("e => e.tagName.toLowerCase()")
        if tag == "select":
            await target.select_option(label=answer)
        else:
            await target.fill(answer)
        return True
    return False
