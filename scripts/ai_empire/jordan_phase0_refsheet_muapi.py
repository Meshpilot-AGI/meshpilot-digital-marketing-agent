#!/usr/bin/env python3
"""Phase-0 reference-sheet builder for the AI influencer pipeline (MuAPI).

Takes a LOCKED face (the candidate the operator picked) and regenerates
the SAME person at multiple angles + expressions via MuAPI nano-banana
(identity-preserving image edit). The result is the persona's
turnaround/reference sheet — the consistency anchor that every future
post is generated against (passed back as the reference image set so the
character never drifts).

Contract (mirrors apps/ugc muapi.submit): POST {base}/{endpoint} with
{prompt, images_list:[face_url], image_url:face_url} -> request_id;
GET predictions/{id}/result -> {status, outputs:[url]}.

Usage:
    MUAPI_API_KEY=... python influencer_phase0_refsheet.py drharry \
        --face https://cdn.muapi.ai/outputs/<id>.jpg
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

MUAPI_BASE = os.environ.get("MUAPI_API_BASE", "https://api.muapi.ai/api/v1")
# nano-banana = strong identity-preserving multi-image edit (per the UGC
# muapi module); seedream-v4 is the fallback if nano drifts.
EDIT_ENDPOINT = os.environ.get("MUAPI_EDIT_ENDPOINT", "nano-banana")

# The turnaround views. Each keeps the EXACT locked identity and varies
# only pose/expression — this is what the consistency gate later checks
# generated posts against.
VIEWS = {
    "jordan": [
        "the exact same man, identical face, short dark hair with natural texture, light stubble, friendly but direct capable expression - front view, neutral calm expression, henley or button-down",
        "the exact same man, identical face - front view, warm genuine slight smile",
        "the exact same man, identical face - three-quarter view facing left, capable expression",
        "the exact same man, identical face - three-quarter view facing right, determined",
        "the exact same man, identical face - left side profile, calm grounded",
        "the exact same man, identical face - upper body, friendly direct, rolled sleeves, modest setting",
    ],
    "drharry": [
        "the exact same man, identical face, beard, saffron-orange turban, round glasses — front view, neutral calm expression",
        "the exact same man, identical face and turban — front view, warm genuine smile",
        "the exact same man, identical face and turban — three-quarter view facing left",
        "the exact same man, identical face and turban — three-quarter view facing right",
        "the exact same man, identical face and turban — left side profile",
        "the exact same man, identical face and turban — looking gently down and to the side as if talking to a dog, soft smile",
    ],
    "noor": [
        "the exact same woman, identical face and styling, cream shawl — front view, neutral calm expression",
        "the exact same woman, identical face — front view, warm genuine smile",
        "the exact same woman, identical face — three-quarter view facing left",
        "the exact same woman, identical face — three-quarter view facing right",
        "the exact same woman, identical face — left side profile",
        "the exact same woman, identical face — looking gently down with a soft smile as if greeting a dog",
    ],
}
_SUFFIX = (
    ". Preserve the person's identity EXACTLY — same face shape, features, short dark hair, light stubble (locked to jordan-locked-face.jpg #1), "
    "skin tone, hair. Ultra-realistic candid photography, soft natural skin texture with visible pores and subtle imperfections, no airbrushing, photorealistic, high detail, subtle film grain, authentic human, dslr, consistent lighting, plain soft "
    "neutral background, head-and-shoulders, no text, no logos."
)


def _headers() -> dict[str, str]:
    key = (os.environ.get("MUAPI_API_KEY") or "").strip()
    if not key:
        sys.exit("MUAPI_API_KEY not set.")
    return {"x-api-key": key, "Content-Type": "application/json"}


async def _one(client: httpx.AsyncClient, face: str, view: str, idx: int) -> str:
    prompt = view + _SUFFIX
    try:
        sub = await client.post(
            f"{MUAPI_BASE}/{EDIT_ENDPOINT}",
            headers=_headers(),
            json={"prompt": prompt, "images_list": [face], "image_url": face},
        )
        if sub.status_code >= 400:
            return f"[{idx}] submit {sub.status_code}: {sub.text[:160]}"
        rid = sub.json().get("request_id") or sub.json().get("id")
        if not rid:
            return f"[{idx}] no request_id: {sub.text[:160]}"
        for _ in range(120):
            await asyncio.sleep(3)
            j = (await client.get(f"{MUAPI_BASE}/predictions/{rid}/result", headers=_headers())).json()
            st = (j.get("status") or "").lower()
            if st in ("completed", "succeeded", "success"):
                outs = j.get("outputs") or []
                return str(outs[0]) if outs else f"[{idx}] no outputs"
            if st in ("failed", "error", "cancelled"):
                return f"[{idx}] {st}: {j.get('error')}"
        return f"[{idx}] poll timed out"
    except Exception as e:  # noqa: BLE001
        return f"[{idx}] error: {e}"


async def _run(persona: str, face: str) -> None:
    views = VIEWS[persona]
    labels = ["front-neutral", "front-smile", "3/4-left", "3/4-right", "side-profile", "with-dog-gaze"]
    print(f"# reference sheet · persona={persona} · model={EDIT_ENDPOINT}")
    print(f"# locked face: {face}\n")
    async with httpx.AsyncClient(timeout=60) as client:
        results = await asyncio.gather(*[_one(client, face, v, i + 1) for i, v in enumerate(views)])
    print("## turnaround views — verify the SAME person holds across all:\n")
    for i, (lab, r) in enumerate(zip(labels, results), 1):
        print(f"{i}. [{lab}] {r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("persona", choices=sorted(VIEWS))
    ap.add_argument("--face", required=True, help="locked face image URL")
    args = ap.parse_args()
    asyncio.run(_run(args.persona, args.face))


if __name__ == "__main__":
    main()
