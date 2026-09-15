"""Job Bank Canada — the federal jobs service (jobbank.gc.ca).

The highest-coverage single source for Canadian roles, and a public service rather than a
commercial board: no key, no login, no ToS grey area. The feed is ATOM despite "rss" in its path.

robots.txt sets `Crawl-delay: 5` and does not disallow the feed path. We honour that delay between
every request INCLUDING the first — a public service run on tax money deserves the courtesy more
than a commercial board does, not less.

The feed's own location filter is unreliable (a city name measurably fails to narrow results), so
searches run nationwide and `filters.location_ok` does the geography.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from glitch_signal.agent.jobs.canonical import canonical_url

FEED_URL = "https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed"
INTER_REQUEST_DELAY_S = 5.0
_TIMEOUT = 25

_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_LINK = re.compile(r'<link[^>]*href="([^"]+)"', re.I)
_UPDATED = re.compile(r"<updated>(.*?)</updated>", re.S | re.I)
_SUMMARY = re.compile(r"<summary[^>]*>(.*?)</summary>", re.S | re.I)
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
# The summary is the only place Job Bank puts location and employer — the <title> is the bare job
# title. Labels are bolded HTML, so parse them rather than the title string.
_FIELD = {
    "location": re.compile(r"Location:\s*</strong>\s*(.*?)\s*(?:<br|<strong|$)", re.S | re.I),
    "employer": re.compile(r"Employer:\s*</strong>\s*(.*?)\s*(?:<br|<strong|$)", re.S | re.I),
    "salary": re.compile(r"Salary:\s*</strong>\s*(.*?)\s*(?:<br|<strong|$)", re.S | re.I),
}


def _text(raw: str) -> str:
    """Unwrap CDATA, strip tags, unescape entities — in that order.

    Order matters: a naive tag-strip run first eats `<![CDATA[ ... ]]>` whole, because it opens with
    `<` and closes with `>`. That silently emptied every title.
    """
    import html

    if not raw:
        return ""
    parts = _CDATA.findall(raw)
    s = " ".join(parts) if parts else raw
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _canadian(loc: str | None) -> str | None:
    """Job Bank lists Canadian roles ONLY, and writes locations as "Milton (ON)" — a province code,
    never the country. A country-level allow-list would reject every row. Rather than teach the
    shared filter 13 province abbreviations (and "ON" is a 2-letter token that collides), state the
    fact the source already guarantees: this row is in Canada.
    """
    if not loc:
        return "Canada"
    return loc if "canada" in loc.lower() else f"{loc}, Canada"


def _field(summary_raw: str, name: str) -> str | None:
    m = _FIELD[name].search(summary_raw or "")
    if not m:
        return None
    val = _text(m.group(1))
    return val or None


async def fetch(keyword: str, *, max_pages: int = 3, **_: Any) -> list[dict]:
    import httpx

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, trust_env=False) as c:
        for page in range(1, max_pages + 1):
            # Honoured before the FIRST request too, not only between pages.
            await asyncio.sleep(INTER_REQUEST_DELAY_S)
            qs = urlencode({"searchstring": keyword, "sort": "M", "page": page})
            r = await c.get(f"{FEED_URL}?{qs}", headers={"user-agent": "meshpilot-jobs/1.0"})
            if r.status_code != 200:
                break
            entries = _ENTRY.findall(r.text)
            if not entries:
                break
            for e in entries:
                link = _LINK.search(e)
                url = canonical_url(link.group(1) if link else "")
                if not url:
                    continue
                tm = _TITLE.search(e)
                sm = _SUMMARY.search(e)
                summary_raw = sm.group(1) if sm else ""
                um = _UPDATED.search(e)
                out.append({"source": "jobbank_ca", "canonical_url": url,
                            "company": _field(summary_raw, "employer"),
                            "title": _text(tm.group(1)) or None,
                            "location": _canadian(_field(summary_raw, "location")),
                            "posted_at": (um.group(1).strip() if um else None),
                            "jd_text": _text(summary_raw) or None})
    return out
