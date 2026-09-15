"""Lever public application form (`jobs.lever.co/{site}/{id}/apply`).

Lever's apply POST needs the employer's Super Admin key, so again the public form is the candidate's
only route. Lever's field names are also stable (`name`, `email`, `phone`, `resume`), and it uses a
single full-name field where Greenhouse splits first/last.
"""
from __future__ import annotations

import structlog

from glitch_signal.agent.jobs.drivers import browser as bx
from glitch_signal.agent.jobs.drivers.greenhouse import _place_answer

log = structlog.get_logger()

_FIELDS = {
    "full_name": ["input[name='name']", "input#name"],
    "email": ["input[name='email']", "input#email", "input[type='email']"],
    "phone": ["input[name='phone']", "input#phone", "input[type='tel']"],
}
_RESUME = ["input[name='resume']", "input[type='file']"]
_SUBMIT = ["button[type='submit']", "input[type='submit']", "button.template-btn-submit"]


def apply_url(url: str) -> str:
    """Lever postings link to the description; the form lives at `/apply`."""
    u = (url or "").rstrip("/")
    return u if u.endswith("/apply") else f"{u}/apply"


class LeverDriver:
    """Implements `submit.SubmissionDriver`."""

    def __init__(self, *, identity: dict, live: bool = False, screenshot_dir: str | None = None):
        self.identity = identity
        self.live = live
        self.screenshot_dir = screenshot_dir

    async def submit(self, package: dict) -> dict:
        from playwright.async_api import async_playwright

        url = apply_url(package["url"])
        async with async_playwright() as pw:
            browser_, ctx, page = await bx.new_page(pw)
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await bx.assert_no_blockers(page)

                for key, sels in _FIELDS.items():
                    val = self.identity.get(key)
                    if not val:
                        continue
                    for sel in sels:
                        loc = page.locator(sel).first
                        if await loc.count():
                            await loc.fill(str(val))
                            break

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

                unplaced = [q for q, a in (package.get("answers") or {}).items()
                            if not await _place_answer(page, q, str(a))]
                if unplaced:
                    return {"ok": False,
                            "failure_reason": f"could not place approved answers: {unplaced[:3]}",
                            "evidence": await bx.evidence_from(page)}

                shot = f"{self.screenshot_dir}/lever-{package.get('application_id')}.png" if self.screenshot_dir else None
                if not self.live:
                    ev = await bx.evidence_from(page, shot)
                    ev["dry_run"] = True
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
                        "failure_reason": None if ok else "no confirmation text after submit"}
            except (bx.BlockedByCaptchaError, bx.RequiresAccountError) as exc:
                return {"ok": False, "failure_reason": str(exc), "evidence": {"url": page.url}}
            finally:
                await ctx.close()
                await browser_.close()
