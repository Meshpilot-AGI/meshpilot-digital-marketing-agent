"""SEO-4 — the scheduled loop. It refuses more often than it runs, and that is the design."""
from __future__ import annotations

import pathlib

import pytest

from glitch_signal.agent.cron import capabilities as caps
from glitch_signal.agent.seo import run

SITEMAP = """<?xml version="1.0"?><urlset>
  <url><loc>https://example.com</loc></url>
  <url><loc>https://example.com/tools/firm-drawdown-calculator</loc></url>
  <url><loc>https://example.com/prop-firms/apex</loc></url>
</urlset>"""

BLOG = """export const blog: BlogPost[] = [
  { slug: 'trailing-drawdown-explained', title: 'Trailing drawdown, explained' },
]"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "public").mkdir()
    (tmp_path / "src" / "data").mkdir(parents=True)
    (tmp_path / "public/sitemap-en.xml").write_text(SITEMAP)
    (tmp_path / "src/data/blog.ts").write_text(BLOG)
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(run, "_enabled", lambda: True)
    monkeypatch.setattr(run, "_cfg", lambda b, n, d="": d)
    monkeypatch.setattr("glitch_signal.agent.positioning.get", lambda *a, **k: _wrap(""))


# ── reading the site, rather than guessing at it ──
def test_site_links_come_from_the_sites_own_sitemap(repo):
    """Not a guess and not a model's memory: the paths the site actually serves."""
    assert run.site_links(repo) == ["/", "/tools/firm-drawdown-calculator", "/prop-firms/apex"]


def test_a_missing_sitemap_reads_as_no_vocabulary(tmp_path):
    assert run.site_links(str(tmp_path)) == []


def test_existing_posts_are_read_so_a_topic_is_not_repeated(repo):
    slugs, titles = run.existing_posts(repo)
    assert slugs == ["trailing-drawdown-explained"]
    assert titles == ["Trailing drawdown, explained"]


# ── the refusals, each with its own named reason ──
async def test_the_kill_switch_refuses_before_anything_is_authored(monkeypatch, repo):
    monkeypatch.setattr(run, "_enabled", lambda: False)
    assert (await run.run_publish("b", {"repo": repo}))["skipped"] == "seo_disabled"


async def test_no_checkout_refuses_rather_than_failing_mid_git(tmp_path):
    """The expected outcome on the API's own runtime, which has no repo, no npm and no gh."""
    res = await run.run_publish("b", {"repo": str(tmp_path)})
    assert res["skipped"] == "no_repo"


async def test_a_repo_without_a_sitemap_refuses_rather_than_inventing_links(tmp_path):
    """Authoring with no link vocabulary is exactly what produced invented internal paths the first
    time. Refusing is better than a post full of plausible 404s."""
    (tmp_path / ".git").mkdir()
    res = await run.run_publish("b", {"repo": str(tmp_path)})
    assert res["skipped"] == "no_sitemap"


async def test_an_empty_topic_stops_the_run(monkeypatch, repo):
    async def _none(*a, **k):
        return ""

    monkeypatch.setattr(run, "pick_topic", _none)
    res = await run.run_publish("b", {"repo": repo})
    assert res["skipped"] == "no_topic"


# ── the happy path, and the one duplicate guard that matters ──
class _Post:
    slug, title = "new-post", "New post"


async def _author_ok(*a, **k):
    return _Post(), []


async def test_a_duplicate_slug_is_named_rather_than_left_to_git(monkeypatch, repo):
    class _Dupe:
        slug, title = "trailing-drawdown-explained", "x"

    monkeypatch.setattr(run, "pick_topic", _dummy_topic)
    monkeypatch.setattr("glitch_signal.agent.seo.generate.author",
                        lambda *a, **k: _wrap((_Dupe(), [])))
    monkeypatch.setattr("glitch_signal.agent.seo.generate.facts_for", lambda *a, **k: _wrap(""))
    res = await run.run_publish("b", {"repo": repo})
    assert res["published"] is False and "already published" in res["reason"]


async def test_dry_run_authors_but_never_touches_the_repo(monkeypatch, repo):
    monkeypatch.setattr(run, "pick_topic", _dummy_topic)
    monkeypatch.setattr("glitch_signal.agent.seo.generate.author", lambda *a, **k: _wrap((_Post(), [])))
    monkeypatch.setattr("glitch_signal.agent.seo.generate.facts_for", lambda *a, **k: _wrap(""))
    before = pathlib.Path(repo, "src/data/blog.ts").read_text()
    res = await run.run_publish("b", {"repo": repo, "dry_run": True})
    assert res["authored"] and not res["published"] and res["reason"] == "dry_run"
    assert pathlib.Path(repo, "src/data/blog.ts").read_text() == before


async def _wrap(v):
    return v


async def _dummy_topic(*a, **k):
    return "how trailing drawdown interacts with weekend gaps"


# ── the registry ──
def test_both_capabilities_are_schedulable():
    assert "seo_publish" in caps.names() and "seo_settle" in caps.names()


def test_publishing_into_someone_elses_repo_demands_the_publish_capability():
    assert caps.required_capabilities("seo_publish") == frozenset({"publish"})


def test_settling_is_not_bundled_into_publishing():
    """The run that publishes does not get to mark its own homework in the same breath."""
    assert caps.required_capabilities("seo_settle") == frozenset()
    assert "seo_settle" not in caps.REQUIRED_CAPABILITIES["seo_publish"]


def test_seo_publish_gets_headroom_for_the_sites_own_gates():
    from glitch_signal.agent.cron.service import timeout_for

    assert timeout_for("seo_publish") == 1800


# ── read against the REAL site file, not only a fixture ──
REAL = pathlib.Path.home() / "dev/glitch-executor/glitch-trade-app"


@pytest.mark.skipif(not (REAL / "src/data/blog.ts").exists(), reason="site checkout not present")
def test_the_real_blog_file_parses_to_its_real_posts():
    """A fixture proves the regex matches the fixture. This proves it matches the file that ships —
    which mixes hand-written single-quoted TS with our own JSON-shaped output, and puts `title:` on
    nested blocks and on the type declaration too."""
    slugs, titles = run.existing_posts(str(REAL))
    assert len(slugs) >= 10
    assert len(titles) == len(slugs)
    assert all(len(t) > 10 and "string" not in t for t in titles)


@pytest.mark.skipif(not (REAL / "public/sitemap-en.xml").exists(), reason="site checkout not present")
def test_the_real_sitemap_yields_the_real_url_vocabulary():
    links = run.site_links(str(REAL))
    assert len(links) > 50
    assert "/tools/firm-drawdown-calculator" in links      # the path the model once invented
    assert "/tools/drawdown-calculator" not in links       # what it invented instead


# ── one post in flight (SEO-6) ──
async def test_a_post_awaiting_review_blocks_the_next_one(monkeypatch, repo):
    """Every post inserts at the same anchor — the top of the array — so two open PRs always
    conflict. #558 and #559 both landed on it and #559 could not be rebased at all. Serialising
    removes the conflict class instead of teaching the publisher to resolve it."""
    from glitch_signal.agent.seo import track

    async def _open(brand_id, **kw):
        return [{"slug": "already-open", "pr_url": "https://example.test/pr/1"}]

    monkeypatch.setattr(track, "unsettled", _open)
    res = await run.run_publish("b", {"repo": repo})
    assert res["skipped"] == "post_in_flight"
    assert res["waiting_on"] == ["https://example.test/pr/1"]


async def test_nothing_in_flight_lets_the_cycle_proceed(monkeypatch, repo):
    from glitch_signal.agent.seo import track

    async def _none(brand_id, **kw):
        return []

    monkeypatch.setattr(track, "unsettled", _none)
    monkeypatch.setattr(run, "pick_topic", _dummy_topic)
    monkeypatch.setattr("glitch_signal.agent.seo.generate.author", lambda *a, **k: _wrap((_Post(), [])))
    monkeypatch.setattr("glitch_signal.agent.seo.generate.facts_for", lambda *a, **k: _wrap(""))
    res = await run.run_publish("b", {"repo": repo, "dry_run": True})
    assert res.get("authored") is True


async def test_a_dry_run_without_a_brand_does_not_query_for_open_prs(monkeypatch, repo):
    """No brand means no track record to consult — a harness run should not need a database."""
    monkeypatch.setattr(run, "pick_topic", _dummy_topic)
    monkeypatch.setattr("glitch_signal.agent.seo.generate.author", lambda *a, **k: _wrap((_Post(), [])))
    monkeypatch.setattr("glitch_signal.agent.seo.generate.facts_for", lambda *a, **k: _wrap(""))
    res = await run.run_publish("", {"repo": repo, "dry_run": True})
    assert res.get("skipped") != "post_in_flight"
    assert res.get("authored") is True
