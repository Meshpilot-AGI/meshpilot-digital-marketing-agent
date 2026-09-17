"""Shared browser plumbing for the ATS drivers.

Playwright lives ONLY in the submitter image (see `submitter/Dockerfile`); the API service never
imports it. The import is therefore deferred into the functions, so the main package still imports
cleanly everywhere else — including in CI, where Playwright is not installed.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

log = structlog.get_logger()

NAV_TIMEOUT_MS = 45_000
ACTION_TIMEOUT_MS = 15_000

# If any of these are present, we STOP. A CAPTCHA means the site wants a human, and defeating it is
# out of scope permanently (design § 7) — not merely unimplemented.
#
# ⚠️ MEASURED 2026-09-15: Lever's public apply form serves reCAPTCHA, so this check fires on EVERY
# Lever posting and they all come back manual_required. That may be over-cautious — an invisible
# reCAPTCHA v3 is score-based and presents no challenge to a human either, so proceeding past one is
# not "solving" anything. Distinguishing an invisible v3 from a real v2 challenge needs a live
# browser to check visibility, which has not been done. Until it is, the conservative reading stands:
# over-blocking fails toward "the operator applies by hand", under-blocking fails toward a broken or
# abandoned application submitted in their name. Operator decision, recorded rather than guessed.
_CAPTCHA_MARKERS = (
    "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "iframe[title*='challenge']",
    "div.g-recaptcha", "div.h-captcha", "#cf-challenge-running", "iframe[src*='turnstile']",
)

# Presence of these means the form wants an ACCOUNT, which the agent must never create.
_AUTH_MARKERS = ("input[type='password']", "input[name*='password']")


class BlockedByCaptchaError(RuntimeError):
    pass


class RequiresAccountError(RuntimeError):
    pass


async def new_page(playwright: Any, *, headless: bool = True):
    browser = await playwright.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    ctx = await browser.new_context(
        viewport={"width": 1440, "height": 1000},
        # A normal desktop UA. NOT an attempt to defeat bot detection — if a site blocks us we stop
        # and report, we do not escalate into evasion.
        user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"),
    )
    ctx.set_default_timeout(ACTION_TIMEOUT_MS)
    ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    page = await ctx.new_page()
    return browser, ctx, page


async def assert_no_blockers(page: Any) -> None:
    """Refuse to proceed on a CAPTCHA or an account wall. Both are permanent stops, not retries."""
    for sel in _CAPTCHA_MARKERS:
        if await page.locator(sel).count():
            raise BlockedByCaptchaError(f"captcha present ({sel}) — handing back to the operator")
    for sel in _AUTH_MARKERS:
        if await page.locator(sel).count():
            raise RequiresAccountError(f"form wants an account ({sel}) — the agent never creates one")


async def evidence_from(page: Any, screenshot_path: str | None = None) -> dict:
    """What we keep to prove a submission happened. No artifact ⇒ treated as NOT submitted."""
    ev: dict[str, Any] = {"url": page.url}
    try:
        body = await page.locator("body").inner_text(timeout=ACTION_TIMEOUT_MS)
        ev["confirmation_text"] = re.sub(r"\s+", " ", body)[:1500]
    except Exception as exc:  # noqa: BLE001
        ev["confirmation_text_error"] = str(exc)[:200]
    if screenshot_path:
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            ev["screenshot"] = screenshot_path
        except Exception as exc:  # noqa: BLE001
            ev["screenshot_error"] = str(exc)[:200]
    return ev


_SUCCESS_PATTERNS = (
    r"thank you for applying", r"your application (?:has been|was) (?:submitted|received)",
    r"application (?:submitted|received|complete)", r"thanks for (?:applying|your interest)",
    r"we(?:'ve| have) received your application",
)


def looks_submitted(text: str) -> bool:
    """Confirmation heuristics. Deliberately requires an EXPLICIT acknowledgement — a page that
    merely stopped erroring is not proof, and a false positive here means the operator believes an
    application was sent when it was not."""
    t = (text or "").lower()
    return any(re.search(p, t) for p in _SUCCESS_PATTERNS)


# Greenhouse marks a required field by appending "*" to its <label>. Every CUSTOM question is
# rendered as `question_<id>` with no semantic name attribute — measured on Later, DEPT and Flipp,
# 2026-09-17 — so a selector built from `name*='linkedin'` matches nothing and the only durable
# handle is the LABEL TEXT.
_REQUIRED_MARK = "*"

# Labels the driver reliably fills from the brand config via SEMANTIC selectors (`#first_name`,
# `input[type=email]`, …), so asking the answer bank about them would report every application as
# manual_required.
#
# ⚠️ Keep this list to fields whose input really is semantic. It briefly also held
# "where are you currently located" and "location (city)" — and on DEPT's form that question is a
# CUSTOM `question_<id>` with no semantic handle, so excluding it here meant it was neither filled
# by selector NOR offered to the resolver: a REQUIRED field left silently blank in a rehearsal that
# otherwise looked clean (measured 2026-09-17). Anything an employer might render as a custom
# question belongs in the resolver, not here — being asked twice is harmless, being skipped is not.
CORE_LABELS = frozenset({
    "first name", "last name", "preferred first name", "email", "phone", "country",
    "resume/cv", "resume", "cover letter", "attach", "enter manually",
})


def label_key(text: str) -> str:
    """Normalise a form label for comparison: case, whitespace, and the required marker."""
    return " ".join((text or "").split()).rstrip("*").strip().lower().rstrip("?:.")


async def required_questions(page: Any) -> list[dict]:
    """Every REQUIRED question on the form that the driver does not already fill from config.

    Read from the page rather than assumed, because the questions are the employer's, not ours. The
    submitter previously passed the application row's own (empty) answer keys as "the questions",
    so `resolve_answers` was handed an empty list, found nothing missing, and the operator's
    answer-bank rule never evaluated — a form with two required questions would have been submitted
    with both blank (measured on Later, 2026-09-17).
    """
    rows = await page.evaluate("""() => {
        const out = [];
        for (const l of document.querySelectorAll('label')) {
            const text = (l.innerText || '').trim().replace(/\\s+/g, ' ');
            if (!text.endsWith('*')) continue;
            let el = null;
            if (l.htmlFor) el = document.getElementById(l.htmlFor);
            if (!el) el = l.parentElement ? l.parentElement.querySelector('input,select,textarea') : null;
            if (!el) continue;
            out.push({label: text, id: el.id || '', tag: el.tagName.toLowerCase(), type: el.type || ''});
        }
        return out;
    }""")
    return [r for r in (rows or []) if label_key(r.get("label", "")) not in CORE_LABELS]
