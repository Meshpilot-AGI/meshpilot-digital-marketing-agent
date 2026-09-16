"""Indeed via Apify — the one METERED source, and the only one that can spend real money.

Indeed has no public jobs API and its ToS forbids scraping it ourselves. Apify runs a maintained
actor (`misceres/indeed-scraper`, 2.1M runs) and carries that burden commercially, which is exactly
why the design routes Indeed through it rather than through a scraper of our own — see design § 4.
Authenticated scraping from the operator's own IP is not an option we are keeping in reserve; it is
rejected.

**This source is billed per result.** Everything here is built around that single fact:

- `MAX_ITEMS_CEILING` is a hard cap applied AFTER the brand config, so a typo in a config file cannot
  order ten thousand results. The brand chooses a number; it cannot choose an unbounded one.
- One request per query, `run-sync-get-dataset-items`, so a run either returns rows or fails — it
  never leaves an actor running in the background, billing, with nobody reading the result.
- A missing `APIFY_KEY` returns [] and logs, rather than raising. A metered source that is not
  configured should be silent, not an outage.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

from glitch_signal.agent.jobs.canonical import canonical_url

log = structlog.get_logger()

ACTOR = "misceres~indeed-scraper"
ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"

# The actor's own run-sync ceiling is 300s; allow for it plus the fetch, and no more. A hung actor
# must fail this tick rather than hold the whole discovery gather open.
_TIMEOUT = 330

# Per QUERY, not per run. 25 results × a handful of queries is a day's worth of new Canadian
# postings; more than that is paying to re-see yesterday's.
DEFAULT_MAX_ITEMS = 25
MAX_ITEMS_CEILING = 100

# Apify's free plan caps concurrent actor RUNS by total memory, and discovery fires every query at
# once through one `asyncio.gather`. Measured 2026-09-15: six simultaneous queries → two came back
# `402 Payment Required` while the same call succeeded on its own moments later. The 402 is about
# concurrency, not about the balance ($0.63 of a $5 allowance was spent), so the fix is to queue the
# queries rather than to spend more. Two at a time keeps the tick quick without tripping it.
_CONCURRENCY = asyncio.Semaphore(2)


def _text(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    return s or None


async def fetch(query: str, *, country: str = "CA", location: str | None = None,
                max_items: int = DEFAULT_MAX_ITEMS, token: str | None = None,
                client: httpx.AsyncClient | None = None, **_: Any) -> list[dict]:
    """One Indeed search → listings in the common shape. Returns [] if unconfigured."""
    key = token or os.environ.get("APIFY_KEY") or ""
    if not key:
        log.warning("jobs.apify.unconfigured", detail="APIFY_KEY is not set; Indeed source skipped")
        return []
    if not (query or "").strip():
        return []

    # NOT `max_items or DEFAULT`: 0 is falsy, so that spelling turns an explicit `max_items: 0` —
    # which can only mean "don't order any" — into a 25-result BILLED run. On a metered source the
    # falsy-default idiom is a live grenade. Only None means "unspecified".
    requested = DEFAULT_MAX_ITEMS if max_items is None else int(max_items)
    capped = max(1, min(requested, MAX_ITEMS_CEILING))
    payload = {
        "position": query,
        "country": country,
        "maxItems": capped,
        # The actor fetches each posting's full description when asked. Without it every Indeed row
        # would arrive unscorable, exactly as Greenhouse did before `content=true` — the scorer
        # refuses a listing summary, and rightly.
        "parseCompanyDetails": False,
        "saveOnlyUniqueItems": True,
        "followApplyRedirects": False,
    }
    if location:
        payload["location"] = location

    own = client is None
    c = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        async with _CONCURRENCY:
            # The token goes in a HEADER, never in the query string. httpx puts the full URL into
            # the exception message it raises on an error status, and `discover._gather` logs that
            # message — so a `?token=` spelling printed the live Apify key into the logs in
            # plaintext, twice, on the first real run (2026-09-15). Observed, not theorised.
            resp = await c.post(ENDPOINT, headers={"Authorization": f"Bearer {key}"}, json=payload)
        resp.raise_for_status()
        rows = resp.json()
    finally:
        if own:
            await c.aclose()

    out: list[dict] = []
    for r in rows if isinstance(rows, list) else []:
        url = canonical_url(_text(r.get("url")) or _text(r.get("jobUrl")) or "")
        if not url:
            continue
        out.append({
            "source": "indeed",
            "canonical_url": url,
            "company": _text(r.get("company")),
            "title": _text(r.get("positionName")) or _text(r.get("title")),
            "location": _text(r.get("location")),
            "posted_at": _text(r.get("postingDateParsed")) or _text(r.get("date")),
            # `description` is the plain-text JD; `descriptionHTML` is the same thing with markup we
            # would only have to strip again.
            "jd_text": _text(r.get("description")),
        })
    log.info("jobs.apify.fetched", query=query, country=country, requested=capped, got=len(out))
    return out
