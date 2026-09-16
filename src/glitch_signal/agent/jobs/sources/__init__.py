"""Job sources — each returns a list of raw listing dicts; the caller filters, dedups and stores.

A source is deliberately dumb: fetch, map to the common shape, return. Filtering lives in
`filters.py` and dedup in `canonical.py`, so adding a source can never introduce a second,
divergent copy of either rule.

Common shape:
    {source, canonical_url, company, title, location, posted_at, jd_text}

⚠️ Authenticated scraping of LinkedIn or Indeed from our own IP is NOT a source here, deliberately —
it is against their ToS and stakes the operator's own account. See design § 4. LinkedIn arrives as
job-ALERT EMAILS (LinkedIn sends them to us); Indeed arrives via Apify, which carries the scraping.
"""
from __future__ import annotations

from glitch_signal.agent.jobs.sources import apify_indeed, ats, jobbank_ca, linkedin_alerts

REGISTRY = {
    "jobbank_ca": jobbank_ca.fetch,
    "greenhouse": ats.fetch_greenhouse,
    "lever": ats.fetch_lever,
    "ashby": ats.fetch_ashby,
    # ⚠️ The only METERED source — billed per result. See apify_indeed for the caps.
    "indeed": apify_indeed.fetch,
    # LinkedIn sends these to the operator; we read them. We never scrape LinkedIn.
    "linkedin_alerts": linkedin_alerts.fetch,
}


def available() -> list[str]:
    return sorted(REGISTRY)
