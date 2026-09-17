"""JOBS-10 — the two sources added to widen the pool: Indeed via Apify, and LinkedIn alert emails.

The Apify tests are about MONEY (it is the only billed source) and the LinkedIn tests are about the
parser, since no real alert email was reachable to verify against.
"""
from __future__ import annotations

import httpx
import pytest

from glitch_signal.agent.jobs.sources import apify_indeed, linkedin_alerts

# Shaped from a real run against misceres/indeed-scraper, 2026-09-15.
_ROW = {"url": "https://ca.indeed.com/viewjob?jk=7a3929e35e6dca25&from=serp",
        "positionName": "Performance Marketing Manager", "company": "Example Co",
        "location": "Toronto, ON", "postingDateParsed": "2026-09-16T01:20:32.826Z",
        "description": "x" * 4000}


def _client(capture: dict, rows=None):
    async def handler(request: httpx.Request) -> httpx.Response:
        capture["url"] = str(request.url)
        capture["json"] = __import__("json").loads(request.content.decode())
        return httpx.Response(200, json=rows if rows is not None else [_ROW])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_indeed_maps_the_actor_output_to_the_common_shape():
    cap: dict = {}
    rows = await apify_indeed.fetch("performance marketing", token="t", client=_client(cap))
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "indeed" and r["company"] == "Example Co"
    assert r["title"] == "Performance Marketing Manager"
    assert len(r["jd_text"]) == 4000, "a listing with no description is unscorable — take the JD"
    assert "jk=7a3929e35e6dca25" in r["canonical_url"]


async def test_a_config_typo_cannot_order_ten_thousand_billed_results():
    """This is the ONLY source that spends money, and it spends it per RESULT. The brand config
    chooses a number; it does not get to choose an unbounded one."""
    cap: dict = {}
    await apify_indeed.fetch("x", token="t", max_items=999_999, client=_client(cap))
    assert cap["json"]["maxItems"] == apify_indeed.MAX_ITEMS_CEILING
    await apify_indeed.fetch("x", token="t", max_items=0, client=_client(cap))
    assert cap["json"]["maxItems"] == 1


async def test_a_missing_key_is_silence_not_an_outage(monkeypatch):
    """A metered source nobody configured should cost nothing and raise nothing."""
    monkeypatch.delenv("APIFY_KEY", raising=False)
    assert await apify_indeed.fetch("x") == []


async def test_an_empty_query_never_reaches_the_billed_endpoint(monkeypatch):
    monkeypatch.setenv("APIFY_KEY", "t")

    async def boom(*a, **k):
        raise AssertionError("an empty query must not start a billed actor run")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    assert await apify_indeed.fetch("   ") == []


# ── LinkedIn alerts ──

_ALERT = """
<table><tr><td>
<a href="https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=abc%3D&refId=xyz">
  Senior Growth Marketing Manager &middot; Shopify &middot; Toronto, ON (Hybrid)</a>
</td></tr><tr><td>
<a href="https://www.linkedin.com/comm/jobs/view/4987654321/?trackingId=def">
  Performance Marketing Lead &middot; Wealthsimple &middot; Remote</a>
</td></tr></table>
"""


def test_the_alert_parser_pulls_role_company_and_location():
    rows = linkedin_alerts.parse_alert(_ALERT)
    assert len(rows) == 2
    assert rows[0]["title"] == "Senior Growth Marketing Manager"
    assert rows[0]["company"] == "Shopify"
    assert rows[0]["location"].startswith("Toronto")
    assert "4123456789" in rows[0]["canonical_url"]
    assert "trackingId" not in rows[0]["canonical_url"], "per-recipient tracking is not identity"


def test_an_alert_listing_carries_no_jd_and_that_is_deliberate():
    """LinkedIn puts no description in an alert, and fetching one would mean fetching it FROM
    LinkedIn — the thing this source exists to avoid. So these rows are stored and unscorable, the
    same way Job Bank's are (measured: jobbank_ca 0 of 13 scorable, greenhouse 12 of 12). That makes
    this a LEAD source — which companies are hiring — not a listing source."""
    assert all(r["jd_text"] is None for r in linkedin_alerts.parse_alert(_ALERT))


async def test_the_same_role_in_two_daily_alerts_lands_once():
    async def reader(_opts):
        return [_ALERT, _ALERT]

    rows = await linkedin_alerts.fetch({}, reader=reader)
    assert len(rows) == 2, "two messages, the same two roles — not four rows"


async def test_no_mailbox_configured_is_silence_not_an_error(monkeypatch):
    for var in ("LINKEDIN_ALERTS_IMAP_HOST", "LINKEDIN_ALERTS_IMAP_USER",
                "LINKEDIN_ALERTS_IMAP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    assert await linkedin_alerts.fetch({}) == []


def test_a_non_job_linkedin_link_is_not_mistaken_for_a_posting():
    """Alert emails are full of profile, feed and unsubscribe links. Only /comm/jobs/view/<id> is a
    job, and matching anything looser would fill the table with LinkedIn's chrome."""
    noise = ('<a href="https://www.linkedin.com/comm/feed/update/urn:li:activity:123">post</a>'
             '<a href="https://www.linkedin.com/comm/in/someone">profile</a>'
             '<a href="https://www.linkedin.com/comm/unsubscribe?x=1">unsubscribe</a>')
    assert linkedin_alerts.parse_alert(noise) == []


@pytest.mark.parametrize("body", ["", None, "<html><body>no jobs this week</body></html>"])
def test_an_empty_or_jobless_alert_parses_to_nothing(body):
    assert linkedin_alerts.parse_alert(body) == []


async def test_the_api_token_never_appears_in_the_url():
    """Observed live 2026-09-15, not theorised: with `?token=` httpx put the full URL into the
    exception it raised on a 402, `discover._gather` logged that message, and the live Apify key
    landed in the logs in plaintext. The token belongs in a header, where an error message cannot
    carry it."""
    cap: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[])

    await apify_indeed.fetch("x", token="SECRET-KEY",
                             client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert "SECRET-KEY" not in cap["url"]
    assert cap["auth"] == "Bearer SECRET-KEY"


def test_the_dry_run_reports_what_it_filled_not_just_that_it_ran():
    """⚠️ The first live rehearsal (2026-09-17) recorded only "form filled, NOT submitted" plus the
    page body — which on a Greenhouse posting is mostly the job description. It proved the code
    reached the form and stopped; it proved NOTHING about whether name, email, phone, country, city
    and LinkedIn actually landed in the right inputs.

    A rehearsal exists so the operator can see what WOULD be sent. If it cannot answer that, they are
    being asked to trust the exact path they wanted rehearsed."""
    import inspect

    from glitch_signal.agent.jobs.drivers import greenhouse

    src = inspect.getsource(greenhouse.GreenhouseDriver.submit)
    dry = src.split("if not self.live:")[1].split("return")[0]
    for key in ("fields_filled", "fields_missing", "resume_uploaded", "answers_placed"):
        assert key in dry, f"the dry-run evidence must report {key}"
