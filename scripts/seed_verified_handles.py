"""Reproducible write path for verified social handles (`brand_asset.handles`).

Before this script, the only way a handle ever reached the database was a manual, out-of-repository
edit — no migration, seed, or application code could write the column at all (`assets.register` had
no `handles` parameter until this change), so a "verified" handle could vanish the moment someone
re-provisioned the database and nobody would notice until tagging silently stopped.

This reads a plain, committable JSON manifest and writes it through `assets.register`, the same
upsert path every other asset field goes through — reviewable in a diff, and re-runnable on any
environment. It intentionally does NOT ship with real handle values: this repo is open-core, and
more importantly a WRONG handle tags a real stranger's account in public, which is worse than not
tagging at all (see `agent/social/platforms_kb.mention_line`). Populate `manifest_path` with each
company's handles taken from that company's OWN site, one entry at a time, reviewed like any other
change — never guessed, never inferred from a partial match.

Manifest shape:
    {
      "<owner_brand>": {
        "<slug>": {"x": "@Handle", "linkedin": "handle-slug", "_source": "example.com footer"}
      }
    }

Usage:
    python scripts/seed_verified_handles.py path/to/verified_handles.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from glitch_signal.agent import assets


async def seed(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text())
    written = 0
    for owner_brand, firms in manifest.items():
        for slug, handles in firms.items():
            existing = await assets.find(owner_brand, kind="logo", slug=slug)
            if not existing:
                print(f"skip {owner_brand}/{slug}: no registered logo asset to attach handles to")
                continue
            asset = existing[0]
            await assets.register(
                owner_brand, kind="logo", slug=slug, name=asset["name"], url=asset["url"],
                width=asset.get("width"), height=asset.get("height"),
                accent=asset.get("accent"), usage_note=asset.get("usage_note"),
                handles=handles,
            )
            written += 1
            print(f"wrote handles for {owner_brand}/{slug}: {sorted(handles)}")
    return written


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    n = asyncio.run(seed(Path(sys.argv[1])))
    print(f"done: {n} asset(s) updated")


if __name__ == "__main__":
    main()
