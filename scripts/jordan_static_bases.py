#!/usr/bin/env python3
"""Static-ad base images (MuAPI nano-banana, identity-locked).
Square twins for studio-wall + kitchen scenes, wireframe concept in both aspects."""
import asyncio
import pathlib

import httpx

from meshpilot_creative.engines import muapi

ASSET_BASE = "https://media.meshpilot.app/assets/jordan"
REF_URLS = [
    f"{ASSET_BASE}/jordan-locked-face.jpg",
    f"{ASSET_BASE}/jordan-ref-muapi-2.jpg",
    f"{ASSET_BASE}/jordan-ref-muapi-3.jpg",
    f"{ASSET_BASE}/jordan-ref-muapi-5.jpg",
]
OUT = pathlib.Path("/home/ubuntu/ai-empire-blueprint/assets/jordan/ads-static/base")
OUT.mkdir(parents=True, exist_ok=True)

IDENTITY = ("the exact same man as in ALL reference images, identical face, identical hairstyle "
            "with natural texture, identical stubble density, identical eyes and facial structure, ")
RECIPE = (", facing the camera directly, looking into the lens, shot on 85mm lens, shallow depth "
          "of field, soft natural skin texture with visible pores, no airbrushing, photoreal, "
          "subtle film grain, dslr, no makeup")

WALL = "dark henley, half-body standing against a charcoal studio wall, editorial key light with soft amber rim light, arms relaxed, generous empty wall space around him for text"
KITCHEN = "henley, half-body leaning on a kitchen counter with a coffee mug, soft morning light, calm relaxed expression, clean negative space"
WIRE = ("dark editorial half-body portrait where the left side of his face, shoulder and arm dissolve "
        "into glowing amber digital wireframe mesh and drifting particles, right side photoreal, "
        "dark charcoal background with depth, cinematic high contrast, generous dark negative space for text")

JOBS = [
    ("wall-1x1", WALL, "1:1"),
    ("kitchen-1x1", KITCHEN, "1:1"),
    ("wire-1x1", WIRE, "1:1"),
    ("wire-9x16", WIRE, "9:16"),
]


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        for label, scene, aspect in JOBS:
            rid = await muapi.submit("nano-banana", IDENTITY + scene + RECIPE,
                                     images=REF_URLS,
                                     settings_overrides={"aspect_ratio": aspect}, client=client)
            for _ in range(60):
                await asyncio.sleep(5)
                res = await muapi.poll(rid, client=client)
                if res.ok:
                    dest = OUT / f"{label}.jpg"
                    dest.write_bytes((await client.get(res.url)).content)
                    print(label, dest.stat().st_size, "b")
                    break
                if res.status in ("failed", "error", "cancelled"):
                    print(label, "FAILED", str(res.raw)[:150])
                    break
    print("BASES DONE")


asyncio.run(main())
