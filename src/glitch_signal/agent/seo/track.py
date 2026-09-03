"""Earning autonomy (SEO-3) — the stage is derived from evidence, never configured.

The amended AI-SEO program grants the agent the right to merge its own posts only after a measured
track record. This is the measurement. Its central property: **`stage_for()` reads history; there is
no setter.** Nobody can grant autonomy by flipping a flag — the streak has to exist, which is what
makes S0 evidence-gathering rather than ceremony.

**How "zero human edits" is measured.** After a PR closes, count the commits on its branch that were
not the agent's. Zero means the post shipped exactly as proposed. This is deliberately mechanical
rather than a diff of prose: a human who touched the post at all left a commit, and a rewrite and a
typo fix both count as "not shipped as proposed" for promotion purposes — which is the conservative
reading, and the right one when the reward is unsupervised publishing.

⚠️ **Known limit, stated rather than hidden:** an edit made in a *separate* PR after the merge is not
counted. The streak measures "shipped as proposed", not "never subsequently touched". A reviewer who
merges and then quietly fixes it elsewhere would look like a clean record here.
"""
from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

# Promotion thresholds, from the amended program. Consecutive, not cumulative: one edited post resets
# the streak, because the claim being tested is "this reliably ships as proposed" — and a run of
# successes interrupted by a rewrite has not demonstrated that.
S0_TO_S1_CLEAN_POSTS = 5
S1_TO_S2_CLEAN_MERGES = 10

STAGES = ("S0", "S1", "S2")

_RECORD = text(
    "INSERT INTO seo_publication (brand_id, slug, title, stage_at_author, gates, pr_number, "
    "  pr_url, branch) "
    "VALUES (:brand_id, :slug, :title, :stage, CAST(:gates AS jsonb), :pr_number, :pr_url, :branch) "
    "ON CONFLICT (brand_id, slug) DO UPDATE SET "
    "  pr_number = EXCLUDED.pr_number, pr_url = EXCLUDED.pr_url, branch = EXCLUDED.branch, "
    "  gates = EXCLUDED.gates, authored_at = now()"
)

_SETTLE = text(
    "UPDATE seo_publication SET merged_at = :merged_at, closed_unmerged = :closed_unmerged, "
    "  human_edits = :human_edits, notes = :notes "
    "WHERE brand_id = :brand_id AND slug = :slug"
)

_HISTORY = text(
    "SELECT slug, stage_at_author, merged_at, closed_unmerged, human_edits, authored_at "
    "FROM seo_publication WHERE brand_id = :brand_id "
    "  AND (merged_at IS NOT NULL OR closed_unmerged IS TRUE) "
    "ORDER BY authored_at DESC LIMIT 60"
)

_UNSETTLED = text(
    "SELECT slug, pr_number, pr_url, branch, stage_at_author FROM seo_publication "
    "WHERE brand_id = :brand_id AND merged_at IS NULL AND closed_unmerged IS NOT TRUE "
    "ORDER BY authored_at"
)


@dataclass(frozen=True)
class Standing:
    stage: str
    clean_streak: int
    settled: int
    next_threshold: int | None
    reason: str


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


async def record(brand_id: str, *, slug: str, title: str = "", stage: str = "S0",
                 gates: dict | None = None, pr_number: int | None = None, pr_url: str = "",
                 branch: str = "", engine: Any = None) -> bool:
    """Record that a post was authored and proposed. Never raises into the publish path."""
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            await conn.execute(_RECORD, {
                "brand_id": brand_id, "slug": slug, "title": title, "stage": stage,
                "gates": json.dumps(gates or {}), "pr_number": pr_number,
                "pr_url": pr_url, "branch": branch,
            })
        return True
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not fail a publish
        log.warning("seo.track_record_failed", slug=slug, error=str(exc)[:200])
        return False


async def settle(brand_id: str, *, slug: str, merged_at: Any = None,
                 closed_unmerged: bool = False, human_edits: int | None = None,
                 notes: str = "", engine: Any = None) -> bool:
    """Record what happened to a proposed post once its PR closed."""
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            await conn.execute(_SETTLE, {
                "brand_id": brand_id, "slug": slug, "merged_at": merged_at,
                "closed_unmerged": closed_unmerged, "human_edits": human_edits, "notes": notes,
            })
        log.info("seo.track_settled", slug=slug, merged=bool(merged_at), edits=human_edits)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("seo.track_settle_failed", slug=slug, error=str(exc)[:200])
        return False


def _streak(rows: list[dict]) -> int:
    """Consecutive most-recent posts that merged with zero human edits.

    Stops at the first post that was edited, closed unmerged, or whose edits were never counted.
    An uncounted post (`human_edits IS NULL`) breaks the streak deliberately: we cannot claim a clean
    record for something nobody checked.
    """
    n = 0
    for r in rows:
        if r.get("closed_unmerged"):
            break
        if r.get("merged_at") is None:
            break
        if r.get("human_edits") is None or int(r["human_edits"]) != 0:
            break
        n += 1
    return n


async def standing(brand_id: str, *, engine: Any = None) -> Standing:
    """The stage this brand has EARNED, with the evidence behind it.

    Fails to the safest answer: any error, or no history at all, is S0. An agent that cannot read its
    own track record has not demonstrated anything.
    """
    try:
        eng = _engine_or(engine)
        async with eng.connect() as conn:
            rows = [dict(r) for r in
                    (await conn.execute(_HISTORY, {"brand_id": brand_id})).mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("seo.standing_failed", error=str(exc)[:200])
        return Standing("S0", 0, 0, S0_TO_S1_CLEAN_POSTS,
                        "could not read the track record — defaulting to the supervised stage")

    streak = _streak(rows)
    settled = len(rows)
    if settled == 0:
        return Standing("S0", 0, 0, S0_TO_S1_CLEAN_POSTS, "no settled posts yet")

    # S2 requires the S1 run ON TOP of the S0 run: the clean streak must include enough posts that
    # were themselves authored while already trusted to self-merge.
    at_s1 = sum(1 for r in rows[:streak] if r.get("stage_at_author") in ("S1", "S2"))
    if streak >= S0_TO_S1_CLEAN_POSTS and at_s1 >= S1_TO_S2_CLEAN_MERGES:
        return Standing("S2", streak, settled, None,
                        f"{at_s1} consecutive clean self-merges")
    if streak >= S0_TO_S1_CLEAN_POSTS:
        return Standing("S1", streak, settled, S1_TO_S2_CLEAN_MERGES,
                        f"{streak} consecutive posts shipped exactly as proposed")
    return Standing("S0", streak, settled, S0_TO_S1_CLEAN_POSTS,
                    f"{streak} of {S0_TO_S1_CLEAN_POSTS} consecutive clean posts")


async def stage_for(brand_id: str, *, engine: Any = None) -> str:
    """The earned stage. There is no setter — this is the whole point."""
    return (await standing(brand_id, engine=engine)).stage


async def unsettled(brand_id: str, *, engine: Any = None) -> list[dict]:
    """Proposed posts whose PR outcome has not been recorded yet."""
    try:
        eng = _engine_or(engine)
        async with eng.connect() as conn:
            return [dict(r) for r in
                    (await conn.execute(_UNSETTLED, {"brand_id": brand_id})).mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("seo.unsettled_failed", error=str(exc)[:200])
        return []


def human_edits_from_commits(commits: list[dict], agent_logins: tuple[str, ...] = ()) -> int:
    """Count commits on the PR branch that were not the agent's.

    ⚠️ **Identity cannot answer this, and assuming it could would have falsified the first entry.**
    The agent commits through the operator's own git identity, because the repo requires commits
    authored as a real person — so its commit and a human's correction share one GitHub login. The
    first two posts each needed a substantive human fix, and login-matching scored them
    `human_edits: 0`: a clean streak started on the two posts that most needed correcting.

    So the AGENT proves authorship instead, with a trailer the publishing path writes and a human
    editor does not (`publish.AGENT_COMMIT_MARKER`). A commit without it is human. That means a post
    authored before the marker existed reads as fully human-edited — under-crediting rather than
    over-crediting, which is the right direction to be wrong in when the reward is unsupervised
    publishing.

    `agent_logins` is still honoured as a fallback for commits carrying no message body at all.

    Mechanical on purpose otherwise: a rewrite and a typo fix both count as "not shipped as
    proposed".
    """
    from glitch_signal.agent.seo.publish import AGENT_COMMIT_MARKER

    logins = {a.lower() for a in agent_logins if a}
    n = 0
    for c in commits or []:
        body = f"{c.get('messageHeadline', '')}\n{c.get('messageBody', '')}"
        if AGENT_COMMIT_MARKER in body:
            continue
        if body.strip():
            n += 1                      # a real commit message, and it is not the agent's
            continue
        author = ((c.get("authors") or [{}])[0] if isinstance(c.get("authors"), list)
                  else c.get("author") or {})
        login = str((author or {}).get("login") or (author or {}).get("name") or "").lower()
        if login and login not in logins:
            n += 1
    return n


# ── settling: without this the ladder never moves ──
#
# `record()` writes the claim; nothing writes the outcome, and an unsettled post has
# `human_edits IS NULL`, which breaks the streak by design. So a track record that is never settled
# leaves the agent at S0 forever — safe, but also inert. This is the half that closes the loop:
# ask GitHub what happened to each open PR, and write it down.
#
# Deliberately a separate, later act rather than something `publish()` does inline: at publish time
# the PR is seconds old and its outcome does not exist yet. It is polled on a schedule instead.


async def settle_open(brand_id: str, *, repo: str, agent_logins: tuple[str, ...] = (),
                      runner: Callable | None = None, engine: Any = None) -> dict:
    """Ask GitHub what happened to each unsettled PR and record it. Returns a small summary.

    Only settles PRs that have actually closed — an open PR has no outcome yet, and guessing one
    would either invent a clean record or destroy a real streak.
    """
    from glitch_signal.agent.seo import publish as _publish

    runner = runner or _publish._run
    rows = await unsettled(brand_id, engine=engine)
    out = {"checked": len(rows), "merged": 0, "rejected": 0, "still_open": 0, "unreadable": 0}

    for row in rows:
        ref = row.get("pr_url") or row.get("branch") or ""
        if not ref:
            out["unreadable"] += 1
            continue
        code, raw = await runner(
            f"gh pr view {shlex.quote(str(ref))} --json state,mergedAt,commits", repo)
        if code != 0:
            out["unreadable"] += 1
            log.warning("seo.settle_lookup_failed", slug=row.get("slug"), out=raw[:200])
            continue
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            out["unreadable"] += 1
            continue

        state = str(data.get("state") or "").upper()
        if state == "OPEN":
            out["still_open"] += 1
            continue
        merged = state == "MERGED" or bool(data.get("mergedAt"))
        edits = (human_edits_from_commits(data.get("commits") or [], agent_logins)
                 if merged else None)
        await settle(brand_id, slug=row["slug"], merged_at=data.get("mergedAt"),
                     closed_unmerged=not merged, human_edits=edits,
                     notes=f"settled from gh: {state}", engine=engine)
        out["merged" if merged else "rejected"] += 1

    log.info("seo.settled_batch", brand_id=brand_id, **out)
    return out


# ── cycle visibility (SEO-6) ────────────────────────────────────────────────────────────────────
#
# The scheduled cycle's only output was a log file on one machine that nothing reads, so a silent
# failure looked exactly like a quiet day — both produce no PR. Every run now leaves a row, refusals
# included, and the alarm is the GAP between rows rather than any single bad one.

_CYCLE = text(
    "INSERT INTO seo_cycle (brand_id, ok, outcome, detail, slug, pr_url, settled) "
    "VALUES (:brand_id, :ok, :outcome, :detail, :slug, :pr_url, CAST(:settled AS jsonb))"
)

_LAST_CYCLES = text(
    "SELECT ran_at, ok, outcome, detail, slug, pr_url FROM seo_cycle "
    "WHERE brand_id = :brand_id ORDER BY ran_at DESC LIMIT :limit"
)


async def record_cycle(brand_id: str, *, ok: bool, outcome: str, detail: str = "",
                       slug: str = "", pr_url: str = "", settled: dict | None = None,
                       engine: Any = None) -> bool:
    """Record what one cycle did. Never raises into the cycle — bookkeeping must not break the job."""
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            await conn.execute(_CYCLE, {
                "brand_id": brand_id, "ok": ok, "outcome": outcome, "detail": detail[:2000],
                "slug": slug, "pr_url": pr_url, "settled": json.dumps(settled or {}),
            })
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("seo.cycle_record_failed", outcome=outcome, error=str(exc)[:200])
        return False


async def recent_cycles(brand_id: str, *, limit: int = 10, engine: Any = None) -> list[dict]:
    """The last few cycles, newest first. What someone checks when asking "is it still running?"."""
    try:
        eng = _engine_or(engine)
        async with eng.connect() as conn:
            return [dict(r) for r in (await conn.execute(
                _LAST_CYCLES, {"brand_id": brand_id, "limit": limit})).mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("seo.recent_cycles_failed", error=str(exc)[:200])
        return []
