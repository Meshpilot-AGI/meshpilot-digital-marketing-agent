#!/usr/bin/env python3
"""Jordan refsheet with fal.ai (Ayurpet replacement, using flux-pro for better photoreal)."""
import argparse, os, fal_client
from pathlib import Path
import requests

MODEL = "fal-ai/flux-pro/v1.1-ultra"

VIEWS = [
    "front view neutral calm confident direct gaze",
    "front view warm genuine smile",
    "three quarter left capable expression",
    "three quarter right thoughtful",
    "left profile calm",
    "three quarter down soft smile as if at laptop",
]

SUFFIX = " exact Jordan Hale 30yo American short dark hair light stubble friendly direct capable casual henley or button down dark jeans clean boots Texas vibe natural light modest setting, shot on 85mm lens, shallow depth of field, soft natural skin texture with visible pores and subtle imperfections, realistic skin details, no airbrushing, photoreal high detail subtle film grain natural lighting candid trustworthy authentic human dslr no makeup, preserve identity exactly"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--face", required=True)
    p.add_argument("--download", action="store_true")
    args = p.parse_args()
    print(f"# fal refsheet base={args.face} model={MODEL}")
    labels = ["front-neutral","front-smile","34-left","34-right","profile","laptop-gaze"]
    for i, v in enumerate(VIEWS):
        prompt = v + SUFFIX
        h = fal_client.submit(MODEL, arguments={
            "prompt": prompt, "image_url": args.face, "strength": 0.82,
            "num_inference_steps": 28, "guidance_scale": 3.5, "image_size": "portrait_4_3"
        })
        url = h.get()["images"][0]["url"]
        print(f"{i+1}. {labels[i]} {url}")
        if args.download and url.startswith("http"):
            Path("assets/jordan/references").mkdir(parents=True, exist_ok=True)
            (Path("assets/jordan/references") / f"jordan-ref-{labels[i]}.jpg").write_bytes(requests.get(url).content)
            print("  saved")
if __name__ == "__main__": main()
