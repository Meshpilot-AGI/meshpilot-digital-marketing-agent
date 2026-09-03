"""SEO-3 — autonomy is derived from evidence. There is no setter."""
from __future__ import annotations

import datetime as dt

from glitch_signal.agent.seo import track

NOW = dt.datetime(2026, 9, 2, tzinfo=dt.UTC)


class _Conn:
    def __init__(self, sink, rows):
        self._sink, self._rows = sink, rows

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _Res(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Engine:
    def __init__(self, rows=None):
        self.calls, self._rows = [], rows or []

    def begin(self):
        return _Conn(self.calls, self._rows)

    def connect(self):
        return _Conn(self.calls, self._rows)


def _clean(n, stage="S0"):
    return [{"slug": f"p{i}", "stage_at_author": stage, "merged_at": NOW,
             "closed_unmerged": False, "human_edits": 0, "authored_at": NOW} for i in range(n)]


# ── the promotion ladder ──
async def test_no_history_is_supervised():
    st = await track.standing("b", engine=_Engine([]))
    assert st.stage == "S0" and st.clean_streak == 0


async def test_four_clean_posts_do_not_promote():
    st = await track.standing("b", engine=_Engine(_clean(4)))
    assert st.stage == "S0" and st.next_threshold == track.S0_TO_S1_CLEAN_POSTS


async def test_five_clean_posts_earn_self_merge():
    st = await track.standing("b", engine=_Engine(_clean(5)))
    assert st.stage == "S1"
    assert "shipped exactly as proposed" in st.reason


async def test_s2_requires_clean_merges_made_while_already_trusted():
    """S1's run must sit on top of S0's — ten clean posts authored while already self-merging, not
    ten clean supervised ones. Otherwise S0 evidence would promote straight past S1."""
    st = await track.standing("b", engine=_Engine(_clean(15, stage="S0")))
    assert st.stage == "S1"                       # plenty of posts, none of them self-merged

    st2 = await track.standing("b", engine=_Engine(_clean(15, stage="S1")))
    assert st2.stage == "S2"


# ── what breaks a streak ──
async def test_one_edited_post_resets_the_streak():
    """Consecutive, not cumulative: the claim being tested is "this reliably ships as proposed", and
    a run interrupted by a rewrite has not demonstrated that."""
    rows = _clean(2) + [{"slug": "edited", "stage_at_author": "S0", "merged_at": NOW,
                         "closed_unmerged": False, "human_edits": 1, "authored_at": NOW}] + _clean(9)
    st = await track.standing("b", engine=_Engine(rows))
    assert st.clean_streak == 2 and st.stage == "S0"


async def test_a_rejected_post_breaks_the_streak():
    rows = _clean(2) + [{"slug": "rejected", "stage_at_author": "S0", "merged_at": None,
                         "closed_unmerged": True, "human_edits": None, "authored_at": NOW}]
    assert (await track.standing("b", engine=_Engine(rows))).clean_streak == 2


async def test_an_uncounted_post_breaks_the_streak():
    """We cannot claim a clean record for something nobody checked."""
    rows = _clean(1) + [{"slug": "unknown", "stage_at_author": "S0", "merged_at": NOW,
                         "closed_unmerged": False, "human_edits": None, "authored_at": NOW}] + _clean(9)
    assert (await track.standing("b", engine=_Engine(rows))).clean_streak == 1


# ── failing safe ──
async def test_an_unreadable_track_record_is_supervised():
    """An agent that cannot read its own record has not demonstrated anything."""
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")

    st = await track.standing("b", engine=_Boom())
    assert st.stage == "S0" and "defaulting to the supervised stage" in st.reason


def test_there_is_no_way_to_set_the_stage():
    """The central property: autonomy is read from history, never assigned. A setter would make the
    whole ladder decorative."""
    assert not [n for n in dir(track)
                if n.startswith(("set_stage", "promote", "grant"))]


# ── edit counting ──
def test_agent_only_commits_count_as_zero_edits():
    commits = [{"authors": [{"login": "agent-bot"}]}, {"authors": [{"login": "agent-bot"}]}]
    assert track.human_edits_from_commits(commits, agent_logins=("agent-bot",)) == 0


def test_a_single_human_commit_counts():
    commits = [{"authors": [{"login": "agent-bot"}]}, {"authors": [{"login": "tejas"}]}]
    assert track.human_edits_from_commits(commits, agent_logins=("agent-bot",)) == 1


def test_a_typo_fix_counts_the_same_as_a_rewrite():
    """Mechanical on purpose. When the reward is unsupervised publishing, "someone had to touch it"
    is the honest bar, not "how much did they change"."""
    commits = [{"authors": [{"login": "tejas"}]}]
    assert track.human_edits_from_commits(commits, agent_logins=("agent-bot",)) == 1


def test_unknown_author_is_treated_as_human():
    assert track.human_edits_from_commits([{"author": {"name": "Someone"}}], agent_logins=()) == 1


# ── recording ──
async def test_record_is_idempotent_per_slug():
    eng = _Engine()
    await track.record("b", slug="s", title="t", stage="S0", pr_url="u", engine=eng)
    assert "on conflict (brand_id, slug) do update" in eng.calls[0][0].lower()


async def test_recording_never_breaks_a_publish():
    class _Boom:
        def begin(self):
            raise RuntimeError("db down")

    assert await track.record("b", slug="s", engine=_Boom()) is False


# ── settling closes the loop ──
class _Gh:
    def __init__(self, payloads):
        self.payloads, self.cmds = payloads, []

    async def __call__(self, cmd, cwd):
        self.cmds.append(cmd)
        for key, val in self.payloads.items():
            if key in cmd:
                return (0, val) if val else (1, "not found")
        return 1, "no match"


async def test_an_open_pr_is_left_alone():
    """It has no outcome yet. Guessing one would either invent a clean record or destroy a real
    streak."""
    eng = _Engine([{"slug": "s", "pr_number": 1, "pr_url": "u/1", "branch": "b",
                    "stage_at_author": "S0"}])
    out = await track.settle_open("b", repo="/r", runner=_Gh({"u/1": '{"state":"OPEN"}'}), engine=eng)
    assert out["still_open"] == 1
    assert not any("UPDATE" in c[0] for c in eng.calls)


async def test_a_merged_pr_settles_with_its_edit_count():
    eng = _Engine([{"slug": "s", "pr_number": 1, "pr_url": "u/1", "branch": "b",
                    "stage_at_author": "S0"}])
    gh = _Gh({"u/1": '{"state":"MERGED","mergedAt":"2026-09-02T00:00:00Z",'
                     '"commits":[{"authors":[{"login":"agent-bot"}]}]}'})
    out = await track.settle_open("b", repo="/r", agent_logins=("agent-bot",), runner=gh, engine=eng)
    assert out["merged"] == 1
    params = [c[1] for c in eng.calls if c[1] and "human_edits" in c[1]][0]
    assert params["human_edits"] == 0 and params["closed_unmerged"] is False


async def test_a_closed_unmerged_pr_settles_as_rejected():
    eng = _Engine([{"slug": "s", "pr_number": 1, "pr_url": "u/1", "branch": "b",
                    "stage_at_author": "S0"}])
    out = await track.settle_open("b", repo="/r", runner=_Gh({"u/1": '{"state":"CLOSED"}'}), engine=eng)
    assert out["rejected"] == 1
    params = [c[1] for c in eng.calls if c[1] and "closed_unmerged" in c[1]][0]
    assert params["closed_unmerged"] is True and params["human_edits"] is None


async def test_an_unreadable_pr_stays_unsettled_rather_than_guessing():
    eng = _Engine([{"slug": "s", "pr_number": 1, "pr_url": "u/1", "branch": "b",
                    "stage_at_author": "S0"}])
    out = await track.settle_open("b", repo="/r", runner=_Gh({"u/1": ""}), engine=eng)
    assert out["unreadable"] == 1
    assert not any(c[1] and "human_edits" in (c[1] or {}) for c in eng.calls)
