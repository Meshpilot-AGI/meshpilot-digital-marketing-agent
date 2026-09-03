"""One SEO cycle — settle first, then publish. For a host that HAS the site checkout.

⚠️ **This deliberately does not run in the cloud, and that is why it is a script rather than a cron
job.** Publishing is a code change in the site's repo: it needs a git checkout, that site's npm
toolchain, and a `gh` that can open a PR. The API's own runtime (FastAPI Cloud) has none of those, so
a scheduled `seo_publish` there would log `no_repo` forever — a job that looks healthy and does
nothing, which is worse than no job. The cron capabilities exist and are schedulable; what they need
is a host with a checkout, and this is how that host runs them.

**Settle runs BEFORE publish, every cycle, deliberately.** The stage `publish` uses is read from the
track record, so a cycle that publishes before recording what happened to the last PR would author at
a stale stage — and at S0 that is merely wasteful, while at S1 it would mean self-merging on
evidence that has since been contradicted.

Install on a machine with the checkout (launchd on macOS, cron on Linux) — see docs/vendors/seo.md.

    uv run python scripts/run_seo_cycle.py                  # settle, then publish
    uv run python scripts/run_seo_cycle.py --dry-run        # author only, repo untouched
    uv run python scripts/run_seo_cycle.py --settle-only    # record outcomes, publish nothing
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys

# ⚠️ `gh` authenticates from EITHER of these, and either one OVERRIDES its own keyring login. So
# simply loading `.env` into the environment silently replaced a working `gh` auth with a token that
# could not open PRs: the first armed cycle authored a real post, passed all four site gates, pushed
# the branch, and then died on `gh pr create` with "not all refs are readable". Opting in via
# GH_TOKEN alone was not enough — GITHUB_TOKEN had to stop being exported too, which is why this is a
# skip-list rather than a flag on one variable.
#
# A fine-grained PAT needs **Contents: read/write** AND **Pull requests: read/write** on the target
# repo. Repo-level `admin: true` in the REST response is NOT the same thing and is not sufficient.
# `settings.github_token` still reads `.env` through pydantic, so Scout is unaffected by the skip.
_GH_AUTH_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")


def _use_token() -> bool:
    """Opt in once the PAT actually carries those permissions."""
    return os.environ.get("SEO_USE_GITHUB_TOKEN", "").strip().lower() in ("1", "true", "yes")


def _load_env() -> None:
    """Put the repo's `.env` into the process environment before anything reads it.

    ⚠️ **launchd inherits NOTHING from a shell** — no profile, no exports. `settings()` reads `.env`
    through pydantic, but plenty of code reads `os.environ` directly (`llm._key()` for one), and the
    `gh` and `npm` subprocesses get only what this process hands them. Under launchd that meant
    `OPENROUTER_API_KEY not set` on the very first armed run, from a cycle that had "passed" its
    earlier test — because the kill-switch had refused before any of this was reached. A test that
    stops short of the code under test proves nothing about it.

    Secrets stay in the gitignored `.env`, never in the committed plist. Real environment wins, so a
    scheduler or an operator can still override any single value.
    """
    env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _GH_AUTH_KEYS and not _use_token():
            # NOT exported. See below — `gh` reads BOTH of these itself.
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    if _use_token() and os.environ.get("GITHUB_TOKEN") and not os.environ.get("GH_TOKEN"):
        os.environ["GH_TOKEN"] = os.environ["GITHUB_TOKEN"]


_load_env()

from glitch_signal.agent.seo import run  # noqa: E402 — must follow _load_env()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", default="glitch_executor")
    ap.add_argument("--topic", default="", help="skip topic selection and write this one")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--settle-only", action="store_true")
    args = ap.parse_args()

    from glitch_signal.agent.seo import track

    settled = await run.run_settle(args.brand)
    print("settle:", json.dumps(settled, default=str))
    if args.settle_only:
        await track.record_cycle(args.brand, ok=True, outcome="settle_only", settled=settled)
        return 0

    try:
        published = await run.run_publish(args.brand, {"dry_run": args.dry_run,
                                                       **({"topic": args.topic} if args.topic else {})})
    except Exception as exc:  # noqa: BLE001
        # The cycle itself broke. Recorded as `ok=False` so it is distinguishable from a refusal —
        # the whole point of the row is that silence and failure used to look identical.
        print("publish: FAILED", exc)
        await track.record_cycle(args.brand, ok=False, outcome="error", detail=str(exc),
                                 settled=settled)
        raise

    print("publish:", json.dumps(published, default=str))
    # ⚠️ A git or PR failure is NOT a refusal. The first live run recorded `ok=True outcome=refused`
    # for "git step failed … index.lock", which reads as a quiet day and hides a real break — the
    # exact thing the row exists to prevent. A refusal is the cycle DECLINING (`skipped`); anything
    # that got as far as trying and broke is a failure.
    if published.get("published"):
        outcome, ok = "published", True
    elif published.get("skipped"):
        outcome, ok = "refused", True
    elif published.get("authored") is False:
        outcome, ok = "author_failed", True          # the model could not satisfy the contract
    else:
        outcome, ok = "publish_failed", False        # gates, git or PR broke after authoring
    await track.record_cycle(
        args.brand, ok=ok, outcome=outcome,
        # `problems` is the diagnostic field when authoring fails, and it was being dropped: the
        # 06:40 run of 2026-09-03 recorded `author_failed` with an EMPTY detail, so the row said
        # something broke and nothing about what. The reason it failed was in the log only.
        detail=str(published.get("skipped") or published.get("reason")
                   or "; ".join(published.get("problems") or []) or "")[:500],
        slug=str(published.get("slug") or ""), pr_url=str(published.get("pr_url") or ""),
        settled=settled)
    # A refusal is a normal outcome here (disabled, no repo, nothing to say, a post already in
    # flight) — not an error, and exiting non-zero would make a scheduler mail about quiet days.
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
