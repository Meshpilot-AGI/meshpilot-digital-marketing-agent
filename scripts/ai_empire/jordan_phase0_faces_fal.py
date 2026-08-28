#!/usr/bin/env python3
"""Phase-0 face-candidate generator for Jordan Hale using fal.ai (replaces MuAPI).

Generates N high-quality portrait candidates for Jordan using fal.ai Flux models.
Prints the output URLs so the operator can pick the single locked face.
Once locked, run the refsheet script to build the full character_ref_set.

Usage:
    FAL_KEY=... python plans/jordan_phase0_faces_fal.py --count 8
    FAL_KEY=... python plans/jordan_phase0_faces_fal.py --model fal-ai/flux-pro/v1.1-ultra --count 6
"""
from __future__ import annotations

import argparse
import os
import sys

import fal_client

# Good Flux models for photoreal people/candidates (high quality + consistency)
# flux-pro or dev are excellent. Use ultra for best faces.
FACE_MODELS = {
    "flux-dev": "fal-ai/flux/dev",
    "flux-pro": "fal-ai/flux-pro/v1.1",
    "flux-ultra": "fal-ai/flux-pro/v1.1-ultra",
}

# Base prompt for Jordan (from BRAND_PERSONA + locked subject)
BASE_JORDAN = (
    "Photorealistic portrait of a 30 year old American man Jordan Hale, "
    "short dark hair, light stubble, friendly but direct capable expression, "
    "casual rolled-sleeve henley or button-down with dark jeans and clean boots, "
    "grounded relatable Texas vibe, natural golden hour or daylight, modest Austin settings, "
    "no luxury, no bro aesthetic, high detail, cinematic lighting, subtle film grain, photoreal"
)

# Variations to get diverse good candidates (operator picks the best single face)
FACE_VARIANTS = [
    "front view, neutral calm confident expression, direct eye contact, clean professional yet approachable",
    "warm genuine smile, slight head tilt, friendly eyes, soft natural light, henley shirt",
    "three-quarter view, serious capable look, stubble detail, button-down, golden hour",
    "slight smile, looking slightly off camera thoughtfully, relaxed but determined, casual setting",
    "front portrait, confident direct gaze, short hair styled neatly, light stubble, modern yet down-to-earth",
    "warm approachable smile with crinkled eyes, outdoor modest porch or truck tailgate background",
]

def generate_face(model: str, variant: str, idx: int) -> str:
    prompt = f"{BASE_JORDAN}, {variant}"
    try:
        handler = fal_client.submit(
            model,
            arguments={
                "prompt": prompt,
                "num_inference_steps": 30,
                "guidance_scale": 3.5,
                "image_size": "portrait_4_3",
                "seed": 42 + idx,
            },
        )
        result = handler.get()
        if "images" in result and result["images"]:
            return result["images"][0]["url"]
        return f"[{idx}] no images"
    except Exception as e:
        return f"[{idx}] error: {e}"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=6, help="Number of face candidates")
    ap.add_argument("--model", default="fal-ai/flux-pro/v1.1-ultra", choices=list(FACE_MODELS.values()) + list(FACE_MODELS.keys()),
                    help="fal model to use")
    args = ap.parse_args()

    model = FACE_MODELS.get(args.model, args.model)
    print(f"# Jordan Hale face candidates using fal.ai ({model})")
    print("# Pick ONE as the locked face for the refsheet.\n")

    for i in range(min(args.count, len(FACE_VARIANTS))):
        url = generate_face(model, FACE_VARIANTS[i], i + 1)
        print(f"{i+1}. {url}")

    print("\nCopy the best URL and run:")
    print("  python plans/jordan_phase0_refsheet_fal.py --face <chosen-url>")

if __name__ == "__main__":
    main()
