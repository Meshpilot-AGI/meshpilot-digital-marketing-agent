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
    """Records commands; fails the ones named in `fail`, and the ones in `fail_once` exactly once."""

    def __init__(self, fail: set[str] | None = None, fail_once: set[str] | None = None,
                 fail_output: str = ""):
        self.cmds: list[str] = []
        self.fail = fail or set()
        self.fail_once = set(fail_once or ())
        self.fail_output = fail_output
        self.outputs: dict[str, str] = {}

    async def __call__(self, cmd: str, cwd: str):
        self.cmds.append(cmd)
        for f in list(self.fail_once):
            if f in cmd:
                self.fail_once.discard(f)
                return 1, self.fail_output or f"boom: {cmd}"
        if any(f in cmd for f in self.fail):
            return 1, self.fail_output or f"boom: {cmd}"
        for prefix, out in self.outputs.items():
            if cmd.startswith(prefix):
                return 0, out
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


# ── a failed publish must leave the repo as it found it (SEO-7) ──
async def test_a_failed_git_step_restores_the_branch_and_the_file():
    """Observed live: a cycle authored a post, passed all four gates, then died on a transient
    `index.lock` — and left the repo DIRTY and parked on the lane branch. The next cycle would read
    a `blog.ts` that already contains the post and refuse it as a duplicate slug. A publisher that
    fails must leave no trace."""
    store, reader, writer = _io()
    runner = _Fake(fail={"git push"})
    runner.outputs["git rev-parse"] = "main"
    res = await pub.publish(_valid_post(), repo="/repo", stage="S0",
                            runner=runner, reader=reader, writer=writer)
    assert not res.ok
    assert any("checkout -- src/data/blog.ts" in c for c in runner.cmds)
    assert any(c.strip() == "git switch main" for c in runner.cmds)
    assert any("branch -D agent/blog/" in c for c in runner.cmds)


async def test_a_transient_index_lock_is_retried_once():
    """`index.lock` means another git process held the repo for a moment — a pull in another shell,
    an editor, a hook. That is a race, not a failure."""
    store, reader, writer = _io()
    runner = _Fake(fail_once={"git commit"}, fail_output="fatal: Unable to create index.lock")
    res = await pub.publish(_valid_post(), repo="/repo", stage="S0",
                            runner=runner, reader=reader, writer=writer)
    assert res.ok, res.reason
    assert len([c for c in runner.cmds if c.startswith("git commit")]) == 2


async def test_a_failed_pr_keeps_the_pushed_branch_but_restores_the_checkout():
    """The commit is good and pushed; only the PR is missing. Deleting the remote branch would throw
    away work a human can still open a PR from."""
    store, reader, writer = _io()
    runner = _Fake(fail={"pr create"})
    runner.outputs["git rev-parse"] = "main"
    res = await pub.publish(_valid_post(), repo="/repo", stage="S0",
                            runner=runner, reader=reader, writer=writer)
    assert not res.ok and "is pushed" in res.reason
    assert not any("branch -D" in c for c in runner.cmds)
    assert any(c.strip() == "git switch main" for c in runner.cmds)


async def test_a_successful_publish_also_returns_to_the_starting_branch():
    """Observed live: a successful publish left the repo on the lane branch. Harmless that day, but
    the NEXT cycle branches from wherever HEAD is — so today's post silently becomes the base of
    tomorrow's, and nothing catches it until two posts are stacked in one PR."""
    store, reader, writer = _io()
    runner = _Fake()
    runner.outputs["git rev-parse"] = "main"
    res = await pub.publish(_valid_post(), repo="/repo", stage="S0",
                            runner=runner, reader=reader, writer=writer)
    assert res.ok
    assert runner.cmds[-1].strip() == "git switch main"
