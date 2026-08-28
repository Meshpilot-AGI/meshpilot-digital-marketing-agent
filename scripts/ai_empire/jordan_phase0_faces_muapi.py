#!/usr/bin/env python3
"""Phase-0 face-candidate generator for the AI influencer pipeline (MuAPI).

Generates N portrait candidates for a persona via MuAPI (the provider
already wired in the cockpit's creative studio — see
meshpilot_dashboard/routes/creative.py), prints the hosted output URLs
for the operator to pick the locked face. Once chosen, the next step
builds the turnaround/reference sheet (the consistency anchor) — and for
that we'll lean on MuAPI's nano-banana / seedream-v4, which are strong
at character consistency + reference editing.

Contract (mirrors creative.py._muapi_generate_image):
  POST {base}/{endpoint}  (x-api-key)            -> {request_id}
  GET  {base}/predictions/{id}/result            -> {status, outputs:[url]}

Reads MUAPI_API_KEY from the environment (the monorepo .env).

Usage:
    MUAPI_API_KEY=... python influencer_phase0_faces.py drharry --count 6
    MUAPI_API_KEY=... python influencer_phase0_faces.py noor --model imagen4 --count 6
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

MUAPI_BASE = os.environ.get("MUAPI_API_BASE", "https://api.muapi.ai/api/v1")

# model_id -> MuAPI endpoint (subset of creative.py._IMAGE_ENDPOINTS that
# is good for photoreal people).
ENDPOINTS = {
    "seedream-v4": "bytedance-seedream-v4",
    "imagen4":     "google-imagen4",
    "ideogram-v3": "ideogram-v3-t2i",
    "nano-banana": "nano-banana",
    "gpt-image-2": "gpt-image-2-text-to-image",
    "flux-dev":    "flux-dev",
}

# FACE-defining prompts, keyed to the persona bibles (plan §13/§15).
# Each persona maps to a LIST of deliberately-varied variants so the
# operator gets genuinely distinct faces to choose from (same prompt =
# near-identical seedream outputs, nothing to pick between). Once a face
# is locked, ALL variation stops — the chosen face becomes the anchor.
_BASE_HARRY = (
    "soft natural skin texture, shallow depth of field, 85mm lens, "
    "candid, trustworthy, photorealistic, no text, no logos"
)
_BASE_JORDAN = ("Ultra-realistic candid photography of Jordan Hale, exactly 30 year old American man, short dark hair with natural texture, light stubble with subtle skin details, friendly but direct capable expression, casual rolled-sleeve henley or button-down with dark jeans and clean boots, grounded relatable Texas vibe, natural golden hour or daylight, modest Austin settings (truck tailgate, simple porch, coffee shop, laptop desk), shot on 85mm lens, shallow depth of field, soft natural skin texture with visible pores and subtle imperfections, realistic skin details, no airbrushing, photorealistic, high detail, subtle film grain, natural lighting, candid, trustworthy, authentic human, dslr, no makeup")
_BASE_NOOR = (
    "soft natural skin texture, shallow depth of field, 85mm lens, "
    "candid lifestyle portrait, photorealistic, no text, no logos"
)
PROMPTS = {
    "jordan": [
        f"Portrait headshot of Jordan Hale, 30, short dark hair, light stubble, friendly direct expression, henley, modest porch, {_BASE_JORDAN}",
        f"Portrait of Jordan Hale, 30, short dark hair natural texture, capable, button down, truck tailgate golden hour, {_BASE_JORDAN}",
        f"Portrait of Jordan Hale, 30, light stubble, thinking expression, coffee shop, {_BASE_JORDAN}",
        f"Portrait headshot of Jordan Hale, 30, friendly capable, rolled sleeve, simple desk setup, {_BASE_JORDAN}",
        f"Portrait of Jordan Hale, 30, determined, laptop late night warm light, {_BASE_JORDAN}",
        f"Portrait of Jordan Hale, 30, calm free, golden hour outdoors porch, {_BASE_JORDAN}",
    ],
    "drharry": [
        f"Portrait headshot of a warm Sikh (Sardar) British man, 46, deep "
        f"maroon turban, full well-groomed salt-and-pepper beard, kind "
        f"brown eyes, thin wire-frame glasses, gentle smile, modern vet "
        f"clinic background, {_BASE_HARRY}",
        f"Portrait of a friendly Sikh (Sardar) British man, 49, navy-blue "
        f"turban, neatly trimmed greying beard, NO glasses, broad warm "
        f"smile, outdoors in a leafy West London park, soft daylight, "
        f"{_BASE_HARRY}",
        f"Portrait headshot of a distinguished Sikh (Sardar) British man, "
        f"50, light grey turban, longer flowing grey beard, calm kind "
        f"expression, glasses on a cord, warm home study background, "
        f"{_BASE_HARRY}",
        f"Portrait of an approachable Sikh (Sardar) British man, 45, royal "
        f"blue turban, dark beard with grey streaks, square modern "
        f"glasses, smiling, navy vet fleece, bright clinic, {_BASE_HARRY}",
        f"Portrait headshot of a warm Sikh (Sardar) British man, 47, "
        f"charcoal-black turban, medium full greying beard, soft eyes, "
        f"no glasses, gentle reassuring smile, neutral studio backdrop, "
        f"{_BASE_HARRY}",
        f"Portrait of a cheerful Sikh (Sardar) British man, 48, "
        f"saffron-orange turban, neat greying beard, thin round glasses, "
        f"big genuine smile, holding a stethoscope, clinic background, "
        f"{_BASE_HARRY}",
    ],
    "noor": [
        f"Portrait of a modern Gulf-Arab woman, 28, warm confident smile, "
        f"loosely draped cream shawl, soft natural makeup, airy Dubai "
        f"apartment, amber daylight, {_BASE_NOOR}",
        f"Portrait of an elegant Gulf-Arab woman, 30, relaxed smile, "
        f"neutral-beige modest modern outfit, hair softly framed, sunny "
        f"Dubai balcony, {_BASE_NOOR}",
        f"Portrait of a friendly Gulf-Arab woman, 29, soft draped taupe "
        f"shawl, gentle smile, minimal jewellery, bright living room with "
        f"plants, {_BASE_NOOR}",
        f"Portrait of an aspirational Gulf-Arab woman, 27, light grey "
        f"modern abaya-style top, warm open smile, café setting softly "
        f"blurred, {_BASE_NOOR}",
        f"Portrait of a poised Gulf-Arab woman, 31, ivory shawl, calm "
        f"confident expression, soft daylight, neutral studio backdrop, "
        f"{_BASE_NOOR}",
        f"Portrait of a relatable Gulf-Arab woman, 29, sand-toned casual "
        f"modest outfit, big genuine smile, outdoors at a Dubai beach at "
        f"golden hour, {_BASE_NOOR}",
    ],
}


def _headers() -> dict[str, str]:
    key = (os.environ.get("MUAPI_API_KEY") or "").strip()
    if not key:
        sys.exit("MUAPI_API_KEY not set in environment.")
    return {"x-api-key": key, "Content-Type": "application/json"}


async def _one(client: httpx.AsyncClient, endpoint: str, prompt: str,
               aspect: str, idx: int) -> str | None:
    try:
        sub = await client.post(
            f"{MUAPI_BASE}/{endpoint}",
            headers=_headers(),
            json={"prompt": prompt, "aspect_ratio": aspect},
        )
        if sub.status_code >= 400:
            return f"[{idx}] submit {sub.status_code}: {sub.text[:160]}"
        rid = (sub.json().get("request_id") or sub.json().get("id"))
        if not rid:
            return f"[{idx}] no request_id: {sub.text[:160]}"
        for _ in range(100):  # ~5 min @3s
            await asyncio.sleep(3)
            res = await client.get(
                f"{MUAPI_BASE}/predictions/{rid}/result", headers=_headers()
            )
            j = res.json()
            st = (j.get("status") or "").lower()
            if st in ("completed", "succeeded", "success"):
                outs = j.get("outputs") or []
                return str(outs[0]) if outs else f"[{idx}] no outputs"
            if st in ("failed", "error", "cancelled"):
                return f"[{idx}] {st}: {j.get('error')}"
        return f"[{idx}] poll timed out"
    except Exception as e:  # noqa: BLE001
        return f"[{idx}] error: {e}"


async def _run(persona: str, model: str, count: int, aspect: str) -> None:
    endpoint = ENDPOINTS[model]
    variants = PROMPTS[persona]
    # Cycle through the variant prompts up to `count` (one distinct face
    # per variant). count defaults to len(variants).
    n = count or len(variants)
    chosen = [variants[i % len(variants)] for i in range(n)]
    print(f"# {n} VARIED candidates · persona={persona} · model={model} ({endpoint})\n")
    async with httpx.AsyncClient(timeout=60) as client:
        results = await asyncio.gather(
            *[_one(client, endpoint, p, aspect, i + 1) for i, p in enumerate(chosen)]
        )
    print(f"## {persona} candidates — open each, pick the locked face:\n")
    for i, (p, r) in enumerate(zip(chosen, results), 1):
        # show the distinguishing words of each variant so the operator
        # can map URL -> look at a glance.
        tag = p.split(",")[1].strip() if "," in p else ""
        print(f"{i}. {r}   ({tag})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("persona", choices=sorted(PROMPTS))
    ap.add_argument("--model", choices=sorted(ENDPOINTS), default="seedream-v4")
    ap.add_argument("--count", type=int, default=0, help="0 = one per variant")
    ap.add_argument("--aspect", default="3:4")
    args = ap.parse_args()
    asyncio.run(_run(args.persona, args.model, args.count, args.aspect))


if __name__ == "__main__":
    main()
