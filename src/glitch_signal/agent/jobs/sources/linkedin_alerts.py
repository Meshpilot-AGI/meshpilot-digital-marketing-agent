"""LinkedIn — via the job-ALERT EMAILS LinkedIn sends the operator. We never scrape LinkedIn.

The distinction is the whole design (§ 4): LinkedIn *sends* these messages to a mailbox the operator
owns, and reading your own mail is not scraping. Authenticated scraping from our own IP would breach
LinkedIn's ToS and stake the operator's account on it; it is rejected, not deferred.

⚠️ **An alert email carries no job description — and that bounds what this source can be.** LinkedIn
puts a title, a company, a location and a link in the message, and nothing else. `score.py` refuses
anything under `MIN_JD_CHARS`, so a listing that arrives only from here is STORED BUT UNSCORABLE, the
same way Job Bank's rows are (measured 2026-09-15: jobbank_ca 0 of 13 scorable, greenhouse 12 of 12).
Fetching the description would mean fetching it from LinkedIn, which is the thing we refuse.

So read this source honestly: it is a **lead** source, not a listing source. Its value is telling the
operator WHICH COMPANIES are hiring for their titles, so those companies' ATS boards — which do carry
full descriptions — can be added to `jobs.ats_boards`. A row from here that is never matched on an
ATS board stays unscored, and that is the expected outcome, not a defect to paper over.

⚠️ **UNVERIFIED against a real message.** No LinkedIn mail exists in the mailbox this session could
reach (searched 2026-09-15: zero LinkedIn messages, zero job-alert messages of any kind), so the
parser is built against LinkedIn's published alert-link format and tested on a constructed fixture.
The first real alert should be checked against it before this source is trusted.
"""
from __future__ import annotations

import html
import re
from typing import Any

import structlog

from glitch_signal.agent.jobs.canonical import canonical_url

log = structlog.get_logger()

# LinkedIn's alert emails link each role as /comm/jobs/view/<id> (the `comm` segment marks a link
# that came from a notification). The numeric id is the stable job identity; everything after it is
# per-recipient tracking, which `canonical_url` strips.
_JOB_LINK = re.compile(r"https://[\w.]*linkedin\.com/comm/jobs/view/(\d+)[^\s\"'<>]*", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Anchor text in these emails is "<title> · <company> · <location>" — LinkedIn uses a middle dot as
# the separator in the notification templates. Split on it rather than guessing at line breaks.
_SEP = re.compile(r"\s*[·•]\s*")


def _plain(fragment: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", fragment or ""))).strip()


def parse_alert(body_html: str) -> list[dict]:
    """One alert email's HTML → listings in the common shape (no jd_text — see the module docstring)."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _JOB_LINK.finditer(body_html or ""):
        job_id = m.group(1)
        url = canonical_url(f"https://www.linkedin.com/jobs/view/{job_id}")
        if not url or url in seen:
            continue
        seen.add(url)
        # The anchor's text sits after the href, up to the closing tag. Take a bounded window rather
        # than parsing the whole document: these emails are table-nested to a depth that makes a
        # real HTML parse cost more than it returns, and a wrong window only loses the title.
        # Start AFTER the tag closes, not after the URL: the regex stops at the quote, so a window
        # opened at m.end() begins with `">` and that punctuation lands in the parsed job title.
        rest = body_html[m.end():]
        gt = rest.find(">")
        tail = rest[gt + 1: gt + 601] if 0 <= gt <= 40 else rest[:600]
        text = _plain(tail.split("</a>")[0] if "</a>" in tail else tail)
        parts = [p for p in _SEP.split(text) if p]
        out.append({
            "source": "linkedin_alerts",
            "canonical_url": url,
            "title": parts[0] if parts else None,
            "company": parts[1] if len(parts) > 1 else None,
            "location": parts[2] if len(parts) > 2 else None,
            "posted_at": None,
            # Deliberately absent. See the module docstring: there is no honest way to fill this.
            "jd_text": None,
        })
    return out


async def fetch(options: dict | None = None, *, reader: Any = None, **_: Any) -> list[dict]:
    """Read recent LinkedIn alert emails and parse them. Returns [] when no mailbox is configured.

    `reader` is injected so the mailbox credential is the ONLY thing this source needs from the
    outside — and so the parser is testable without one. No reader means no mailbox has been wired
    yet, which is a configuration state, not an error.
    """
    opts = options or {}
    if reader is None:
        reader = _imap_reader(opts)
    if reader is None:
        log.warning("jobs.linkedin_alerts.unconfigured",
                    detail="no mailbox configured (jobs.linkedin_alerts.imap_* / LINKEDIN_ALERTS_*)")
        return []

    bodies = await reader(opts)
    out: list[dict] = []
    for body in bodies:
        out.extend(parse_alert(body))
    # Cross-message dedup: the same role appears in consecutive daily alerts.
    uniq: dict[str, dict] = {}
    for item in out:
        uniq.setdefault(item["canonical_url"], item)
    log.info("jobs.linkedin_alerts.parsed", messages=len(bodies), listings=len(uniq))
    return list(uniq.values())


def _imap_reader(opts: dict) -> Any:
    """Build an IMAP reader from config/env, or None when nothing is configured.

    IMAP with an app password rather than OAuth on purpose: it is the only route the operator can
    set up alone. An OAuth client would need consent screens and a token exchange, and neither an
    agent nor an assistant should be creating accounts or handling the operator's password — so the
    credential is something they mint themselves and paste into the environment.
    """
    import os

    host = opts.get("imap_host") or os.environ.get("LINKEDIN_ALERTS_IMAP_HOST")
    user = opts.get("imap_user") or os.environ.get("LINKEDIN_ALERTS_IMAP_USER")
    password = os.environ.get("LINKEDIN_ALERTS_IMAP_PASSWORD")
    if not (host and user and password):
        return None
    folder = opts.get("folder", "INBOX")
    days = int(opts.get("days", 7))

    async def _read(_o: dict) -> list[str]:
        import asyncio  # noqa: PLC0415

        return await asyncio.to_thread(_imap_fetch, host, user, password, folder, days)

    return _read


def _imap_fetch(host: str, user: str, password: str, folder: str, days: int) -> list[str]:
    """Blocking IMAP fetch of recent LinkedIn messages. Read-only: the mailbox is never modified."""
    import email
    import imaplib
    from datetime import UTC, datetime, timedelta

    since = (datetime.now(UTC) - timedelta(days=max(1, days))).strftime("%d-%b-%Y")
    bodies: list[str] = []
    with imaplib.IMAP4_SSL(host) as m:
        m.login(user, password)
        # readonly=True is load-bearing: opening a mailbox read-write marks messages \Seen, which
        # would silently change what the operator sees in their own inbox.
        m.select(folder, readonly=True)
        _typ, data = m.search(None, f'(FROM "linkedin.com" SINCE {since})')
        for num in (data[0].split() if data and data[0] else [])[-50:]:
            _typ, raw = m.fetch(num, "(BODY.PEEK[])")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            for part in msg.walk() if msg.is_multipart() else [msg]:
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True) or b""
                    bodies.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return bodies
