"""SEO-2 — the publish path: contract first, gates second, git last."""
from __future__ import annotations

import json

import pytest

from glitch_signal.agent.seo import publish as pub
from glitch_signal.agent.seo.post import Post

_BLOG = """export type BlogBlock = never
export const blog: BlogPost[] = [
  { "slug": "existing-post" },
]
export const blogBySlug = Object.fromEntries(blog.map((p) => [p.slug, p]))
"""


def _valid_post(slug="a-new-post") -> Post:
    return Post(
        slug=slug, title="A title", lede="A short lede answering the question directly.",
        tldr="The direct answer.", author_slug="ryan", published_at="2026-09-02",
        reading_minutes=8, tags=["t"],
        blocks=[
            {"type": "p", "text": "Prose citing $100,000 and 10%."},
            {"type": "stat", "stat": "A $100,000 account has a $10,000 cushion.",
             "context": "Static floors do not move.",
             "sourceUrl": "https://example.com/ref", "sourceLabel": "Ref"},
            *[{"type": "h2", "text": t, "id": t} for t in ("a", "b", "c", "d")],
            {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
            {"type": "antiPattern", "title": "Not this", "text": "What it does not solve."},
            {"type": "cite", "sources": [
                {"label": "t", "url": "/tools/x"}, {"label": "f", "url": "/prop-firms/"},
                {"label": "b", "url": "/brokers/overview"},
                {"label": "r", "url": "https://example.com/ref"}]},
        ],
        faq=[{"q": f"Q{i}?", "a": f"A{i}."} for i in range(5)])


class _Fake:
    """Records commands; fails the ones named in `fail`."""

    def __init__(self, fail: set[str] | None = None):
        self.cmds: list[str] = []
        self.fail = fail or set()

    async def __call__(self, cmd: str, cwd: str):
        self.cmds.append(cmd)
        if any(f in cmd for f in self.fail):
            return 1, f"boom: {cmd}"
        if cmd.startswith("gh pr create"):
            return 0, "https://github.com/x/y/pull/1"
        return 0, "ok"


def _io():
    store = {"src/data/blog.ts": _BLOG}

    def reader(p):
        return store[[k for k in store if p.endswith(k)][0]]

    def writer(p, s):
        store[[k for k in store if p.endswith(k)][0]] = s

    return store, reader, writer


# ── insertion ──
def test_post_is_inserted_at_the_top_of_the_array():
    out = pub.insert_post(_BLOG, _valid_post())
    assert out.index("a-new-post") < out.index("existing-post")   # newest first
    assert out.count("export const blog: BlogPost[] = [") == 1   # array not duplicated


def test_duplicate_slug_is_refused_not_overwritten():
    """`blogBySlug` is built with Object.fromEntries — a duplicate slug silently drops a post."""
    dup = _BLOG.replace('"slug": "existing-post"', '"slug": "a-new-post"')
    with pytest.raises(ValueError, match="already exists"):
        pub.insert_post(dup, _valid_post())


def test_missing_anchor_refuses_rather_than_guessing():
    with pytest.raises(ValueError, match="layout changed"):
        pub.insert_post("export const other = []", _valid_post())


# ── ordering: contract before the file is touched ──
async def test_contract_failure_never_touches_the_repo():
    """Writing a failing post then reverting leaves a dirty tree and a confusing branch."""
    store, reader, writer = _io()
    runner = _Fake()
    bad = _valid_post()
    bad.faq = []                                  # fails the FAQ clause
    res = await pub.publish(bad, repo="/repo", runner=runner, reader=reader, writer=writer)
    assert not res.ok and "editorial contract" in res.reason
    assert store["src/data/blog.ts"] == _BLOG     # untouched
    assert runner.cmds == []                      # no git, no gates


async def test_gate_failure_stops_before_any_git_command():
    store, reader, writer = _io()
    runner = _Fake(fail={"typecheck"})
    res = await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    assert not res.ok and "verification gate failed" in res.reason
    assert not any(c.startswith("git") for c in runner.cmds)


async def test_a_failed_gate_leaves_the_file_in_place_for_debugging():
    """A human debugging a typecheck failure needs the file that produced it."""
    store, reader, writer = _io()
    runner = _Fake(fail={"typecheck"})
    await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    assert "a-new-post" in store["src/data/blog.ts"]


async def test_gates_stop_at_the_first_failure():
    """Later gates run against a build the earlier one already called broken."""
    runner = _Fake(fail={"lint"})
    results, _ = await pub.run_gates("/repo", runner=runner)
    assert results == {"typecheck": True, "lint": False}
    assert not any("schemas" in c for c in runner.cmds)


# ── the happy path, and where it stops ──
async def test_s0_opens_a_pr_and_does_not_merge():
    """S0 is the whole point: the agent authors, a human merges. Autonomy is earned."""
    store, reader, writer = _io()
    runner = _Fake()
    res = await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    assert res.ok and res.stage == "S0"
    assert res.pr_url.endswith("/pull/1")
    assert any(c.startswith("gh pr create") for c in runner.cmds)
    assert not any("pr merge" in c for c in runner.cmds)


async def test_it_never_commits_to_main():
    store, reader, writer = _io()
    runner = _Fake()
    await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    switch = [c for c in runner.cmds if c.startswith("git switch")][0]
    assert switch == "git switch -c agent/blog/a-new-post"
    assert "--base main" in [c for c in runner.cmds if "gh pr create" in c][0]


async def test_git_failure_is_reported_not_swallowed():
    store, reader, writer = _io()
    runner = _Fake(fail={"git push"})
    res = await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    assert not res.ok and "git step failed" in res.reason


async def test_pr_body_states_the_stage_and_gate_results():
    store, reader, writer = _io()
    runner = _Fake()
    await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    body = [c for c in runner.cmds if "gh pr create" in c][0]
    assert "Stage S0" in body and "typecheck" in body


def test_emitted_post_is_valid_json_inside_the_file():
    out = pub.insert_post(_BLOG, _valid_post())
    start = out.index("{", out.index("BlogPost[] = ["))
    depth, end = 0, start
    for i, ch in enumerate(out[start:], start):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            end = i + 1
            break
    assert json.loads(out[start:end])["slug"] == "a-new-post"


# ── the stage is earned, not passed (SEO-3) ──
async def test_publish_reads_the_earned_stage_when_a_brand_is_given(monkeypatch):
    """A caller cannot decide it is time for autonomy — the track record decides."""
    from glitch_signal.agent.seo import track

    async def _stage(brand_id, **kw):
        return "S1"

    async def _record(*a, **kw):
        return True

    monkeypatch.setattr(track, "stage_for", _stage)
    monkeypatch.setattr(track, "record", _record)
    store, reader, writer = _io()
    runner = _Fake()
    res = await pub.publish(_valid_post(), repo="/repo", brand_id="b",
                            runner=runner, reader=reader, writer=writer)
    assert res.stage == "S1"
    assert any("pr merge" in c for c in runner.cmds)      # earned self-merge


async def test_s0_still_never_merges(monkeypatch):
    from glitch_signal.agent.seo import track

    async def _stage(brand_id, **kw):
        return "S0"

    async def _record(*a, **kw):
        return True

    monkeypatch.setattr(track, "stage_for", _stage)
    monkeypatch.setattr(track, "record", _record)
    store, reader, writer = _io()
    runner = _Fake()
    res = await pub.publish(_valid_post(), repo="/repo", brand_id="b",
                            runner=runner, reader=reader, writer=writer)
    assert res.stage == "S0"
    assert not any("pr merge" in c for c in runner.cmds)


async def test_a_failed_auto_merge_leaves_the_pr_open_rather_than_losing_it(monkeypatch):
    from glitch_signal.agent.seo import track

    async def _stage(brand_id, **kw):
        return "S1"

    async def _record(*a, **kw):
        return True

    monkeypatch.setattr(track, "stage_for", _stage)
    monkeypatch.setattr(track, "record", _record)
    store, reader, writer = _io()
    runner = _Fake(fail={"pr merge"})
    res = await pub.publish(_valid_post(), repo="/repo", brand_id="b",
                            runner=runner, reader=reader, writer=writer)
    assert res.ok and res.pr_url            # the post still exists as a reviewable PR
    assert "left open for review" in res.reason


async def test_no_brand_id_defaults_to_supervised():
    """A dry run or a test harness gets the safe stage, not an assumed one."""
    store, reader, writer = _io()
    runner = _Fake()
    res = await pub.publish(_valid_post(), repo="/repo", runner=runner, reader=reader, writer=writer)
    assert res.stage == "S0"
