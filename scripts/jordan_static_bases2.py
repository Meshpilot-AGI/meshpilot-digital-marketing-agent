#!/usr/bin/env python3
"""Non-face static bases v2 (Tejas: only the wire concept keeps the face).
Pure scene shots via MuAPI seedream-v4, both aspects."""
import asyncio
import pathlib

import httpx

from meshpilot_creative.engines import muapi

OUT = pathlib.Path("/home/ubuntu/ai-empire-blueprint/assets/jordan/ads-static/base")
OUT.mkdir(parents=True, exist_ok=True)

SYSTEM = ("premium dark tech advertisement background, a sleek laptop on a dark walnut desk "
          "displaying a glowing amber automation dashboard with connected agent nodes and flowing "
          "data lines, subtle amber circuit traces on the dark surface, moody cinematic lighting, "
          "large dark negative space in the lower half for text overlay, no people, no readable "
          "text anywhere, photoreal commercial product photography, high detail")

NIGHTDESK = ("an empty modern home office at night, nobody there, empty chair, laptop open showing "
             "a glowing e-commerce dashboard with a rising sales graph, smartphone beside it lit up "
             "with notification badges, warm amber screen glow in a dark cozy room, shallow depth "
             "of field, cinematic, no people, no readable text anywhere, large dark negative space "
             "in the lower half for text overlay, photoreal, high detail")

JOBS = [
    ("wall-1x1", SYSTEM, "1:1"),
    ("wall-9x16", SYSTEM, "9:16"),
    ("kitchen-1x1", NIGHTDESK, "1:1"),
    ("kitchen-9x16", NIGHTDESK, "9:16"),
]


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        for label, prompt, aspect in JOBS:
            rid = await muapi.submit("seedream-v4", prompt,
                                     settings_overrides={"aspect_ratio": aspect}, client=client)
            for _ in range(60):
                await asyncio.sleep(5)
                res = await muapi.poll(rid, client=client)
                if res.ok:
                    (OUT / f"{label}.jpg").write_bytes((await client.get(res.url)).content)
                    print(label, "ok")
                    break
                if res.status in ("failed", "error", "cancelled"):
                    print(label, "FAILED", str(res.raw)[:120])
                    break
    print("BASES V2 DONE")


asyncio.run(main())
