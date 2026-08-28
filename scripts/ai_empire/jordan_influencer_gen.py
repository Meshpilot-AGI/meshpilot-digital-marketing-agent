#!/usr/bin/env python3
"""
Jordan Hale AI Influencer Daily Generator + Performance Loop.

Standalone content factory for @jordanhaleai promoting the AI Empire Blueprint.

Modeled directly on the Ayurpet AI influencer implementation in the main
Mesh Pilot repo (glitch-grow-ads-agent-private):

- docs/social-pipeline/AI_CONTENT_PIPELINE_BLUEPRINT.md
  (scout → plan → asset_generator → assembler → QC → publish → engage → learn)
- scripts/ayurpet_meta_daily_to_memory.py (daily ingest of performance to memory/facts)
- scripts/ayurpet_derived_insights_refresh.py (cross insights + reflection)
- src/social_agent/scripts/influencer_*.py and plans for persona lock + pipeline

This script is intentionally simple and file-based (no DB dependency) so it
can run on the ai-empire-blueprint repo or a laptop. It produces ready-to-use
prompt packs for Flux / ComfyUI / Kling + Claude captions.

Core loop (run this as the "machine"):
1. Scout/plan next day using pillars + story beats + prior winners.
2. Generate full asset prompts (locked Jordan visuals + variations).
3. "Assemble" by writing day-N prompt file.
4. (Manual) Post via IG app or API.
5. Log performance (likes, saves, comments, ROAS if ads).
6. Learn: reflect weekly on what won → update rotation.

The generated assets + this log become the proof bank for the Blueprint itself.

Usage examples:
  python plans/jordan_influencer_gen.py --day 1 --generate
  python plans/jordan_influencer_gen.py --batch 1 7 --generate
  python plans/jordan_influencer_gen.py --log-perf --day 3 --likes 312 --saves 41 --comments 27 --notes "strong hook on 45min"
  python plans/jordan_influencer_gen.py --learn

Outputs go to ../../data/ (relative to this script) or override with --data-dir.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List

# LOCKED FACE (user choice 2026-07-04): jordan-locked-face.jpg (MuAPI front-neutral #1)
# ONLY this is the canonical identity reference. 2-6 are supporting variations only.
# All prompts MUST be prefixed with Base Locked Subject AND conditioned on the reference stills (esp. locked face #1).
# Full details and enforcement: docs/JORDAN_CHARACTER_REFERENCES.md + BRAND_PERSONA.md
# --- Locked visuals from BRAND_PERSONA.md (single source of truth) ---
LOCKED_BASE = (
    "Ultra-realistic candid photography of Jordan Hale, exactly 30 year old American man, short dark hair with natural texture, light stubble with subtle skin details, friendly but direct capable expression, casual rolled-sleeve henley or button-down with dark jeans and clean boots, grounded relatable Texas vibe, natural golden hour or daylight, modest Austin settings (truck tailgate, simple porch, coffee shop, laptop desk), shot on 85mm lens, shallow depth of field, soft natural skin texture with visible pores and subtle imperfections, realistic skin details, no airbrushing, photorealistic, high detail, subtle film grain, natural lighting, candid, trustworthy, authentic human, dslr, no makeup, "
)

LOCKED_NEGATIVE = "blurry, deformed, extra limbs, cartoon, 3d, lowres, plastic skin, waxy, synthetic, overly smooth skin, doll-like, mannequin, airbrushed, AI artifacts, generated, illustration, painting, drawing, watermark, text overlay on face, childlike, corporate, flashy cars, luxury excess, perfect skin"

PILLARS = [
    ("proof", 0.40, "Proof & Results - numbers, before/after, case patterns"),
    ("machine", 0.30, "Behind the Machine - prompts, workflows, tools, automation"),
    ("personal", 0.20, "Personal Story - grind, breakthrough, shift, current freedom"),
    ("offer", 0.10, "Direct / Soft offer - link in bio, blueprint mention"),
]

# Story beats from JORDAN_HALE_STORY.md (use to anchor content)
BEATS = [
    ("breaking", "The Breaking Point - late nights grinding digital marketing/dropshipping, old plays owned me"),
    ("first-try", "Desperate first ugly attempts - inconsistent faces, tiny results, almost quit"),
    ("breakthrough", "The Breakthrough - first consistent LoRA/character (Lila example), believed the machine"),
    ("first-money", "First real money - few thousand while still running other projects"),
    ("machine", "Building the Machine - 30-45 min/day, automation + agents + packaging"),
    ("shift", "The Shift - stopped feeding the old low-margin grind"),
    ("freedom", "Current life + meta proof - low key freedom, the IG account itself is built with the system"),
]

# 7-day starter calendar (from strategy, cleaned/expanded). Extend via rotation.
WEEKLY_TEMPLATE = [
    ("proof", "breaking"),   # Day 1
    ("personal", "first-try"),
    ("machine", "breakthrough"),
    ("proof", "first-money"),
    ("machine", "machine"),
    ("personal", "shift"),
    ("offer", "freedom"),
]

DATA_DIR_DEFAULT = Path(__file__).resolve().parent.parent / "data"
PROMPTS_DIR = DATA_DIR_DEFAULT / "daily_prompts"
LOGS_DIR = DATA_DIR_DEFAULT / "performance"

def ensure_dirs(data_dir: Path) -> None:
    (data_dir / "daily_prompts").mkdir(parents=True, exist_ok=True)
    (data_dir / "performance").mkdir(parents=True, exist_ok=True)

def pillar_for_day(day: int) -> tuple[str, str]:
    """Cycle through pillars with slight bias to proof/machine."""
    idx = (day - 1) % len(PILLARS)
    p = PILLARS[idx]
    return p[0], p[2]

def beat_for_day(day: int) -> tuple[str, str]:
    idx = (day - 1) % len(BEATS)
    return BEATS[idx]

def variation_for_day(day: int, pillar: str) -> str:
    """Add pillar + beat specific modifiers while preserving face lock."""
    mods = {
        "proof": "holding phone or laptop showing stylized revenue numbers, slight relief or confident smile, evening or golden light",
        "machine": "at laptop pointing or gesturing at screen showing prompts and example character images, confident teacher mode, clean daylight",
        "personal": "late night tired-but-determined on laptop in truck or modest desk, or relaxed porch freedom shot with no devices",
        "offer": "clean portrait or casual lifestyle with subtle phone showing IG content, direct relatable gaze, strong CTA energy",
    }
    base_mod = mods.get(pillar, "natural capable expression, modest setting")
    # Cycle a few story-tied extras
    beat_idx = (day - 1) % len(BEATS)
    beat_name = BEATS[beat_idx][0]
    extras = {
        "breaking": "subtle stress in posture, warm dim lighting",
        "first-try": "early frustrated expression with messy notes around",
        "breakthrough": "Whataburger bag on tailgate, focused research look, golden hour",
        "first-money": "truck interior, phone glow, genuine small smile of relief",
        "machine": "screen visible with Claude / Flux examples, organized desk",
        "shift": "decisive calm look, minimal setup, keys or truck in frame",
        "freedom": "relaxed porch or tailgate, arms crossed, pure daylight, zero laptop",
    }
    extra = extras.get(beat_name, "")
    return f"{base_mod}, {extra}".strip(", ")

def build_image_prompt(day: int, pillar: str) -> str:
    var = variation_for_day(day, pillar)
    return f"{LOCKED_BASE}, {var}. {LOCKED_NEGATIVE}"

def build_video_prompt(day: int, pillar: str, image_prompt: str) -> str:
    # Short 6-9s motion prompt for Kling-style. Start from still + subtle motion.
    motion = "subtle natural breathing, slight head turn or smile, calm authentic movement, gentle camera push or handheld feel, no sudden cuts"
    if pillar == "proof":
        motion = "phone screen reveal with numbers animating softly, small satisfied nod, warm light shift"
    elif pillar == "machine":
        motion = "hand gesture toward screen, natural pointing, screen content stays sharp"
    return f"Start from this exact frame: {image_prompt}. Animate with {motion}. 6-9 seconds, vertical 9:16, photoreal, consistent Jordan face lock."

def build_captions(day: int, pillar: str, beat: str) -> List[str]:
    """Return 3 caption variants in Jordan voice (straight, numbers, no hype, relatable marketing background)."""
    base_cta = " Everything is in the $67 Blueprint. Link in bio."
    beat_text = beat[1]
    if pillar == "proof":
        return [
            f"Real patterns, not hype. {beat_text.split(' - ')[0]} I hit first real numbers while still grinding other projects.{base_cta}",
            f"$4.7k first month. $6k+ automated now. Zero team. This is what the data actually looked like when I stopped guessing.{base_cta}",
            f"Most 'AI money' stuff is noise. Here is the documented shape of what worked for me coming from dropshipping.{base_cta}",
        ]
    if pillar == "machine":
        return [
            f"The machine: Claude for characters + personality, Flux/Comfy for lock, Kling for motion, agents for replies. 30-45 min/day once running.{base_cta}",
            f"I went from hours of grinding content to batching on Sunday and letting the system post + reply. Exact loops in the pack.{base_cta}",
            f"Same character factory works for any niche. I give you the full prompt recipes, LoRA recipe, and the daily loop.{base_cta}",
        ]
    if pillar == "personal":
        return [
            f"I was in digital marketing and dropshipping. Long nights. Low margins. The old plays never gave freedom. Then I found this.{base_cta}",
            f"First attempts were garbage. Faces changed every time. Almost quit. Then one focused session with consistent refs changed everything.{base_cta}",
            f"No big audience. No coding background. Heavy AI orchestration only. This is the shift from grind to leverage.{base_cta}",
        ]
    # offer
    return [
        f"Stop buying $27 prompt packs that leave you guessing. The full system (prompts, workflows, agents, packaging) is here.{base_cta}",
        f"If you want the exact files I used to go from stuck to automated, this is it. No fluff. Real background included.{base_cta}",
        f"Built the IG you're looking at with the same methods. Meta truth: the account itself is the demo.{base_cta}",
    ]

def get_day_plan(day: int) -> Dict[str, Any]:
    pillar_key, pillar_desc = pillar_for_day(day)
    beat_key, beat_desc = beat_for_day(day)
    img = build_image_prompt(day, pillar_key)
    vid = build_video_prompt(day, pillar_key, img)
    caps = build_captions(day, pillar_key, (beat_key, beat_desc))
    hook = caps[0][:90] + "..." if len(caps[0]) > 90 else caps[0]
    return {
        "day": day,
        "date": str(date.today()),
        "pillar": pillar_key,
        "pillar_desc": pillar_desc,
        "beat": beat_key,
        "beat_desc": beat_desc,
        "format": "Reel" if pillar_key in ("proof", "machine") else "Carousel" if pillar_key == "personal" else "Static+Reel",
        "hook": hook,
        "image_prompt": img,
        "video_prompt": vid,
        "caption_variants": caps,
        "hashtags": "#AI #MakeMoneyWithAI #Faceless #DigitalProducts #AITools",
        "cta_link": "buildaiempire.com (or current domain)",
        "notes": "Use locked Jordan visuals. Post in Jordan voice. Log performance after 24-48h.",
    }

def write_day_prompts(day: int, data_dir: Path) -> Path:
    plan = get_day_plan(day)
    out_dir = data_dir / "daily_prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"day-{day:02d}.json"
    with open(out_file, "w") as f:
        json.dump(plan, f, indent=2)
    # Also write a human readable .md companion
    md = out_dir / f"day-{day:02d}.md"
    with open(md, "w") as f:
        f.write(f"# Day {day} — {plan['pillar'].upper()} / {plan['beat']}\n\n")
        f.write(f"**Format:** {plan['format']}\n")
        f.write(f"**Hook:** {plan['hook']}\n\n")
        f.write("## Image Prompt (Flux / ComfyUI)\n")
        f.write(f"```\n{plan['image_prompt']}\n```\n\n")
        f.write("## Video Prompt (Kling / image-to-video)\n")
        f.write(f"```\n{plan['video_prompt']}\n```\n\n")
        f.write("## Caption Variants (use one, Jordan voice)\n")
        for i, c in enumerate(plan["caption_variants"], 1):
            f.write(f"{i}. {c}\n\n")
        f.write(f"**Hashtags:** {plan['hashtags']}\n")
        f.write(f"**CTA:** {plan['cta_link']}\n")
    print(f"Wrote prompts for day {day} -> {out_file}")
    return out_file

def log_performance(day: int, likes: int, saves: int, comments: int, notes: str, data_dir: Path) -> None:
    log_dir = data_dir / "performance"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "performance_log.jsonl"
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "day": day,
        "likes": likes,
        "saves": saves,
        "comments": comments,
        "engagement": likes + (saves * 2) + (comments * 3),  # simple weighted
        "notes": notes,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Logged performance for day {day}: {entry}")

def learn_from_logs(data_dir: Path) -> None:
    log_file = data_dir / "performance" / "performance_log.jsonl"
    if not log_file.exists():
        print("No performance log yet. Run --log-perf a few times.")
        return
    entries = []
    with open(log_file) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    if not entries:
        print("Log empty.")
        return
    # Simple reflection (like derived insights)
    sorted_e = sorted(entries, key=lambda e: e.get("engagement", 0), reverse=True)
    print("=== Top performers by weighted engagement ===")
    for e in sorted_e[:5]:
        print(f"  Day {e['day']}: likes={e['likes']} saves={e['saves']} comments={e['comments']} | {e.get('notes','')[:60]}")
    # Pillar hints
    print("\n=== Quick reflection (feed this back into planner) ===")
    print("Double down on days with high saves (saves = strong hook + value).")
    print("Reels (proof/machine) tend to win for cold traffic. Use winners as seed for next batch.")
    print("Update WEEKLY_TEMPLATE or get_day_plan() rotation based on real numbers above.")

def main() -> int:
    p = argparse.ArgumentParser(description="Jordan Hale influencer content gen + learn loop (Ayurpet pattern)")
    p.add_argument("--day", type=int, default=None, help="Specific day number (1-30+)")
    p.add_argument("--batch", nargs=2, type=int, metavar=("START", "END"), help="Generate range e.g. 1 7")
    p.add_argument("--generate", action="store_true", help="Write prompt files for the day(s)")
    p.add_argument("--log-perf", action="store_true", help="Append a performance entry")
    p.add_argument("--likes", type=int, default=0)
    p.add_argument("--saves", type=int, default=0)
    p.add_argument("--comments", type=int, default=0)
    p.add_argument("--notes", type=str, default="")
    p.add_argument("--learn", action="store_true", help="Run simple reflection over logs")
    p.add_argument("--data-dir", type=Path, default=DATA_DIR_DEFAULT)
    args = p.parse_args()

    ensure_dirs(args.data_dir)

    if args.learn:
        learn_from_logs(args.data_dir)
        return 0

    if args.log_perf:
        if args.day is None:
            print("--day required for --log-perf")
            return 2
        log_performance(args.day, args.likes, args.saves, args.comments, args.notes, args.data_dir)
        return 0

    if args.generate:
        if args.batch:
            start, end = args.batch
            for d in range(start, end + 1):
                write_day_prompts(d, args.data_dir)
        elif args.day:
            write_day_prompts(args.day, args.data_dir)
        else:
            print("Use --day N or --batch START END with --generate")
            return 2
        return 0

    # Default: print today's plan
    day = args.day or 1
    plan = get_day_plan(day)
    print(json.dumps(plan, indent=2))
    print("\nTip: add --generate to write files, or --log-perf after posting.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
