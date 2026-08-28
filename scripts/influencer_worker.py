#!/usr/bin/env python3
"""Influencer pipeline worker — runs the end-to-end ticks on a cadence.

The brand-scoped content plan (core.influencer_post_plan) is the queue;
this worker drives discovery → generation → posting for a brand's
personas. Designed to run from a systemd timer (one sweep per invocation)
or as a long-loop (--loop).

Usage:
  # one full sweep (generate next approved + post next ready)
  python influencer_worker.py --brand ayurpet

  # also top up ideas via discovery
  python influencer_worker.py --brand ayurpet --discover

  # discovery only, for one persona
  python influencer_worker.py --brand ayurpet --persona drharry --discover-only

  # long loop (every N seconds)
  python influencer_worker.py --brand ayurpet --loop --interval 300

Env: POSTGRES_BRAIN_URL (plan store), MUAPI_API_KEY (generation),
UPLOAD_POST_API_KEY (posting), DISPATCH_MODE=dry_run to no-op posting.
Run with WorkingDirectory at the social_agent repo root.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from glitch_signal.influencer import pipeline


async def _run(args: argparse.Namespace) -> int:
    if args.discover_only:
        targets = [args.persona] if args.persona else pipeline._brand_personas(args.brand)
        if not targets:
            print(f"no personas declare brand_id={args.brand}", file=sys.stderr)
            return 2
        for pid in targets:
            r = await pipeline.discovery_tick(
                pid, per_pillar=args.per_pillar,
                products=args.product or None,
            )
            print(f"[discovery] {pid}: {r.status} — {r.detail}")
        return 0

    if args.engage_only:
        targets = [args.persona] if args.persona else pipeline._brand_personas(args.brand)
        for r in await pipeline.engagement_tick(args.brand, persona_id=args.persona):
            print(f"[engagement] {r.persona_id}: {r.status} — {r.detail}")
        return 0

    async def one_sweep() -> None:
        results = await pipeline.run_all(
            args.brand, persona_id=args.persona, discover=args.discover,
            per_pillar=args.per_pillar, products=args.product or None,
        )
        for r in results:
            tag = f"{r.persona_id or '-'}#{r.plan_id or '-'}"
            print(f"[{r.stage}] {tag}: {r.status} — {r.detail}")
        if args.engage:
            for r in await pipeline.engagement_tick(args.brand, persona_id=args.persona):
                print(f"[engagement] {r.persona_id}: {r.status} — {r.detail}")

    if not args.loop:
        await one_sweep()
        return 0

    while True:
        try:
            await one_sweep()
        except Exception as e:  # noqa: BLE001
            print(f"sweep error: {e}", file=sys.stderr)
        await asyncio.sleep(args.interval)


def main() -> None:
    ap = argparse.ArgumentParser(description="Influencer pipeline worker")
    ap.add_argument("--brand", required=True, help="brand_id (e.g. ayurpet)")
    ap.add_argument("--persona", help="restrict to one persona_id")
    ap.add_argument("--discover", action="store_true", help="also run discovery this sweep")
    ap.add_argument("--discover-only", action="store_true", help="only run discovery")
    ap.add_argument("--engage", action="store_true", help="also run engagement this sweep")
    ap.add_argument("--engage-only", action="store_true", help="only run engagement (comment replies)")
    ap.add_argument("--per-pillar", type=int, default=2, help="ideas per pillar")
    ap.add_argument("--product", action="append", default=[], help="catalog product (repeatable)")
    ap.add_argument("--loop", action="store_true", help="run forever")
    ap.add_argument("--interval", type=int, default=300, help="loop interval seconds")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
