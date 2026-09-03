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
import sys

from glitch_signal.agent.seo import run


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", default="glitch_executor")
    ap.add_argument("--topic", default="", help="skip topic selection and write this one")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--settle-only", action="store_true")
    args = ap.parse_args()

    settled = await run.run_settle(args.brand)
    print("settle:", json.dumps(settled, default=str))
    if args.settle_only:
        return 0

    published = await run.run_publish(args.brand, {"dry_run": args.dry_run,
                                                   **({"topic": args.topic} if args.topic else {})})
    print("publish:", json.dumps(published, default=str))
    # A refusal is a normal outcome here (disabled, no repo, no topic, duplicate slug) — it is not an
    # error, and exiting non-zero would make a scheduler mail about routine quiet days.
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
