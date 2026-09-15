"""JOBS-2 acceptance — canonicalization, filtering, and the discovery pipeline.

Design: docs/plans/2026-09-15-job-application-agent.md §§ 4, 8.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs.canonical import canonical_url, same_posting
from glitch_signal.agent.jobs.filters import location_ok, passes, title_ok

CFG = {
    "target_titles": ["Performance Marketing", "Growth Marketing", "Paid Media", "PPC", "Marketing Manager"],
    "exclude_titles": ["Product Marketing", "Software Engineer", "Intern"],
    "locations": {"allow": ["Canada", "Toronto", "Ontario", "Remote - Canada", "North America"]},
}


# --- canonicalization: the dedup key -------------------------------------------------

def test_tracking_params_are_stripped():
    a = "https://job-boards.greenhouse.io/acme/jobs/123?utm_source=linkedin&utm_campaign=x&gh_src=abc"
    assert canonical_url(a) == "https://job-boards.greenhouse.io/acme/jobs/123"


def test_identity_params_are_kept():
    """gh_jid IS the posting id on some Greenhouse boards — stripping it would merge distinct roles."""
    u = canonical_url("https://boards.greenhouse.io/acme/jobs/1?gh_jid=9&utm_source=x")
    assert "gh_jid=9" in u
    assert "utm_source" not in u


def test_host_aliases_collapse():
    assert same_posting("https://boards.greenhouse.io/acme/jobs/1",
                        "https://job-boards.greenhouse.io/acme/jobs/1")
    assert same_posting("https://www.linkedin.com/jobs/view/42", "https://linkedin.com/jobs/view/42")
    assert same_posting("https://ca.indeed.com/viewjob?jk=abc", "https://indeed.com/viewjob?jk=abc")


def test_fragment_and_trailing_slash_are_not_identity():
    assert same_posting("https://jobs.lever.co/acme/x/", "https://jobs.lever.co/acme/x#apply")


def test_query_order_is_not_identity():
    assert same_posting("https://x.com/j?a=1&b=2", "https://x.com/j?b=2&a=1")


def test_path_case_is_preserved():
    """ATS job ids are case-sensitive tokens — lowercasing the path would merge two real postings."""
    assert not same_posting("https://jobs.ashbyhq.com/acme/AbC123",
                            "https://jobs.ashbyhq.com/acme/abc123")


def test_scheme_is_normalized_to_https():
    assert canonical_url("http://jobs.lever.co/acme/x") == "https://jobs.lever.co/acme/x"


@pytest.mark.parametrize("bad", ["", "   ", None, "javascript:alert(1)", "mailto:a@b.c", "not a url at all!"])
def test_unusable_urls_return_empty(bad):
    assert canonical_url(bad) == ""


def test_empty_url_is_never_equal_to_itself():
    """Two unparseable URLs must not dedup into one another."""
    assert not same_posting("javascript:void(0)", "mailto:x@y.z")


# --- filtering ------------------------------------------------------------------------

def test_exclusion_beats_inclusion():
    """'Senior Product Marketing Manager' contains 'Marketing Manager'. Product Marketing is a
    different discipline and was 28% of the operator's first real scan."""
    ok, why = title_ok("Senior Product Marketing Manager", CFG)
    assert not ok and "excluded" in why


def test_target_titles_match():
    assert title_ok("Performance Marketing Manager", CFG)[0]
    assert title_ok("Growth Marketing Lead", CFG)[0]


def test_unrelated_title_is_dropped():
    assert not title_ok("Staff Backend Engineer", CFG)[0]


def test_short_keywords_are_word_anchored():
    """'PPC' must not fire inside an unrelated word."""
    assert title_ok("PPC Specialist", CFG)[0]
    assert not title_ok("Appcelerator Developer", CFG)[0]


def test_empty_location_passes():
    """Many ATS boards omit location entirely; missing data is not a signal."""
    assert location_ok("", CFG)[0]
    assert location_ok(None, CFG)[0]


def test_location_allowlist():
    assert location_ok("Toronto, ON", CFG)[0]
    assert location_ok("Remote (Canada)", CFG)[0]
    assert not location_ok("London, United Kingdom", CFG)[0]


def test_multi_city_posting_naming_canada_passes():
    assert location_ok("Vancouver, British Columbia, Canada; London, England", CFG)[0]


def test_passes_requires_both():
    assert passes("Performance Marketing Manager", "Toronto, ON", CFG)[0]
    assert not passes("Performance Marketing Manager", "Berlin, Germany", CFG)[0]
    assert not passes("Product Marketing Manager", "Toronto, ON", CFG)[0]


def test_no_config_is_permissive_not_silently_empty():
    """An unconfigured brand must not silently drop everything."""
    assert title_ok("Anything At All", {})[0]
    assert location_ok("Anywhere", {})[0]


# --- discovery orchestration ----------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_with_no_sources_is_a_noop(monkeypatch):
    from glitch_signal.agent.jobs import discover as disc

    monkeypatch.setattr(disc, "jobs_config", lambda b: {"sources": {}})
    out = await disc.discover("tejas")
    assert out["fetched"] == 0 and out["stored"]["inserted"] == 0
    assert "no sources enabled" in out["note"]


@pytest.mark.asyncio
async def test_discover_filters_and_dedups_before_storing(monkeypatch):
    from glitch_signal.agent.jobs import discover as disc

    same = "https://job-boards.greenhouse.io/acme/jobs/1"
    async def fake(_slug, **_):
        return [
            {"source": "greenhouse", "canonical_url": canonical_url(same + "?utm_source=a"),
             "title": "Performance Marketing Manager", "location": "Toronto, ON"},
            # same posting, different decoration → must collapse
            {"source": "greenhouse", "canonical_url": canonical_url(same + "#apply"),
             "title": "Performance Marketing Manager", "location": "Toronto, ON"},
            # wrong discipline → filtered
            {"source": "greenhouse", "canonical_url": "https://job-boards.greenhouse.io/acme/jobs/2",
             "title": "Product Marketing Manager", "location": "Toronto, ON"},
            # wrong geography → filtered
            {"source": "greenhouse", "canonical_url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "title": "Paid Media Manager", "location": "Berlin, Germany"},
        ]

    monkeypatch.setattr(disc, "jobs_config", lambda b: dict(
        CFG, sources={"ats_boards": True}, ats_boards=[{"provider": "greenhouse", "slug": "acme"}]))
    monkeypatch.setitem(disc.REGISTRY, "greenhouse", fake)

    out = await disc.discover("tejas", dry_run=True)
    assert out["fetched"] == 4
    assert out["kept"] == 1, "one real posting should survive dedup + both filters"
    assert out["filtered_out"] == 3


@pytest.mark.asyncio
async def test_one_failing_source_does_not_lose_the_others(monkeypatch):
    from glitch_signal.agent.jobs import discover as disc

    async def boom(_slug, **_):
        raise RuntimeError("board is down")

    async def good(_slug, **_):
        return [{"source": "lever", "canonical_url": "https://jobs.lever.co/acme/x",
                 "title": "Growth Marketing Manager", "location": "Toronto"}]

    monkeypatch.setattr(disc, "jobs_config", lambda b: dict(
        CFG, sources={"ats_boards": True},
        ats_boards=[{"provider": "greenhouse", "slug": "dead"}, {"provider": "lever", "slug": "acme"}]))
    monkeypatch.setitem(disc.REGISTRY, "greenhouse", boom)
    monkeypatch.setitem(disc.REGISTRY, "lever", good)

    out = await disc.discover("tejas", dry_run=True)
    assert out["kept"] == 1


def test_jobbank_honours_crawl_delay():
    """robots.txt sets Crawl-delay: 5 — it must be honoured, including before the first request."""
    from glitch_signal.agent.jobs.sources import jobbank_ca

    assert jobbank_ca.INTER_REQUEST_DELAY_S >= 5.0


def test_no_authenticated_scraping_source_exists():
    """Design § 4 rejects scraping LinkedIn/Indeed from our own IP. Prove none crept in."""
    from glitch_signal.agent.jobs.sources import REGISTRY

    for name in REGISTRY:
        assert "linkedin" not in name or "alert" in name, f"{name} looks like a LinkedIn scraper"


# --- Job Bank parsing: regressions for three bugs found in live verification ----------

def test_cdata_is_unwrapped_not_stripped_as_a_tag():
    """A naive tag-strip eats `<![CDATA[ ... ]]>` whole — it opens with '<' and closes with '>'.
    That silently emptied EVERY title in live verification."""
    from glitch_signal.agent.jobs.sources.jobbank_ca import _text

    assert _text("<title><![CDATA[marketing manager]]></title>") == "marketing manager"
    assert _text("<![CDATA[digital marketing specialist]]>") == "digital marketing specialist"


def test_location_and_employer_come_from_the_summary_not_the_title():
    """Job Bank's <title> is the bare job title; location/employer are bolded fields in <summary>."""
    from glitch_signal.agent.jobs.sources.jobbank_ca import _field

    summary = ("<![CDATA[<strong>Job number:</strong> 632351488734010384<br />"
               "<strong>Location:</strong> Milton (ON)  <br />"
               "<strong>Employer:</strong> 4Sight Search Solutions Inc.<br />"
               "<strong>Salary:</strong> $60,000.00 to $80,000.00 annually]]>")
    assert _field(summary, "location") == "Milton (ON)"
    assert _field(summary, "employer") == "4Sight Search Solutions Inc."


def test_jobbank_rows_are_tagged_canadian():
    """Job Bank writes "Milton (ON)" — a province code, never the country. A country-level
    allow-list rejected all 25 live rows until the source stated what it already guarantees."""
    from glitch_signal.agent.jobs.sources.jobbank_ca import _canadian

    assert _canadian("Milton (ON)") == "Milton (ON), Canada"
    assert _canadian(None) == "Canada"
    assert _canadian("Toronto, Canada") == "Toronto, Canada", "must not double-append"
    assert location_ok(_canadian("Vancouver (BC)"), CFG)[0]


def test_jobbank_feed_path_is_the_working_one():
    """`/jobsearch/feed/rss` 404s; the live path is `/jobsearch/feed/jobSearchRSSfeed`."""
    from glitch_signal.agent.jobs.sources import jobbank_ca

    assert jobbank_ca.FEED_URL.endswith("/jobsearch/feed/jobSearchRSSfeed")


# --- word-order variants (JOBS-12) -----------------------------------------------------

def test_inverted_titles_match():
    """"Manager, Marketing" is the same job as "Marketing Manager". Substring matching cannot see
    that, and Job Bank's NOC-style titles are full of inversions."""
    cfg = dict(CFG, target_titles=["Marketing Manager"], exclude_titles=[])
    assert title_ok("Manager, Marketing", cfg)[0]
    assert title_ok("Marketing Manager", cfg)[0]
    assert title_ok("Manager - Marketing Operations", cfg)[0]


def test_exclusions_still_beat_word_order_matches():
    """Order-independence is only safe because exclusions are checked FIRST."""
    cfg = dict(CFG, target_titles=["Marketing Manager"], exclude_titles=["Product Marketing"])
    assert not title_ok("Product Marketing Manager", cfg)[0]
    assert not title_ok("Manager, Product Marketing", cfg)[0]


def test_single_word_targets_do_not_become_promiscuous():
    """A one-word target must NOT gain order-independent matching — it would match everything."""
    from glitch_signal.agent.jobs.filters import _all_words_present

    assert not _all_words_present("senior software engineer", "marketing")


def test_unrelated_titles_still_rejected_with_word_order_on():
    cfg = dict(CFG, target_titles=["Marketing Manager"], exclude_titles=[])
    assert not title_ok("Chief Human Resource Officer", cfg)[0]
    assert not title_ok("Student Recruiter", cfg)[0]
