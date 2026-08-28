"""JH-AD-004: scene-by-scene storyboard build (research-backed creative).
Generated B-roll ALLOWED and directed per scene; visual change every ~2s;
approved $2k script; single caption system. Writes /tmp/jordan_ad4.json."""
import asyncio
import json
import os
import time

from meshpilot_creative.engines import heygen

VOICE = os.environ["JORDAN_HEYGEN_VOICE_ID"]
PRIMARY_LOOK = "b4012e41fa0d4b60996d0800a7345a30"

BROLL_BASE = "https://1c76c506.ai-empire-blueprint.pages.dev/jordan"
FILES = [
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-lakehouse-deck.jpg"},
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-home-patio.jpg"},
]

PROMPT = """A 30-second vertical ad reel with high visual velocity: a new shot or visual change roughly every 2 seconds, zero dead air. The selected presenter is the narrator and recurring anchor; you have full creative freedom to GENERATE contextual B-roll scenes between his lines — modern e-commerce and AI imagery that matches each beat. Alternate presenter and B-roll constantly.

SCENE-BY-SCENE STORYBOARD (VO = spoken voiceover; keep the Scene 1 line VERBATIM):

Scene 1 (0-1.5s) — PRESENTER tight to camera, high energy. VO: "I used this hack to hit a $2,000 sales day on my dropshipping store." Bold text card slams in: "$2,000 SALES DAY".
Scene 2 (~2s) — GENERATED B-ROLL: over-the-shoulder laptop shot, clean e-commerce dashboard with sales graph climbing, order notifications popping. VO: "No team."
Scene 3 (~2s) — PRESENTER, shrug, half-grin. VO: "And I can't even code."
Scene 4 (~3s) — GENERATED B-ROLL: hands on a laptop, an AI chat interface writing product listings by itself on screen. VO: "AI agents run the whole thing. They find the products, write the listings..."
Scene 5 (~3s) — GENERATED B-ROLL: phone screen with cha-ching sale notifications stacking up, then shipping boxes by a door. VO: "...process the orders, answer the customers."
Scene 6 (~3s) — PRESENTER, relaxed, settling. VO: "I check in for thirty minutes a day. That's it."
Scene 7 (~2s) — B-ROLL from ATTACHED photo (lakehouse deck), slow push-in. No VO, one beat of calm.
Scene 8 (~5s) — PRESENTER leans in, tiny pause before the line. VO: "And the crazy part? The guy telling you this is AI too. Built with the same system."
Scene 9 (~2s) — GENERATED B-ROLL: quick stylized reveal — the presenter's frame with a subtle digital wireframe/scanline flash, implying he is AI-generated.
Scene 10 (~4s) — PRESENTER, direct, friendly urgency. VO: "It's called the AI Empire Blueprint. Sixty-seven bucks, one time, everything included."
Scene 11 (2s) — END CARD: dark background, centered "buildaiempire.com" and "$67 one-time". VO: "Grab it while it's still sixty-seven. Link below."

This storyboard is a concept to convey — not a rigid timeline. You may refine pacing and shot details, but keep: the verbatim Scene 1 line, the presenter/B-roll alternation, a visual change every ~2 seconds, and the 30-second total.

Target duration: 30 seconds.

CRITICAL ON-SCREEN TEXT (render verbatim, do not rephrase):
- $2,000 SALES DAY
- buildaiempire.com
- $67 one-time

Tone: urgent, confident, slightly conspiratorial — telling a friend about something before it stops working. Zero corporate polish.

CAPTION RULE (CRITICAL): EXACTLY ONE caption system — one styled kinetic caption layer synced to speech, clean white bold sans-serif, amber-yellow (#fbbf24) highlights on "$2,000", "AI agents", "AI too", "$67". Do NOT add any second subtitle track, plain subtitle line, or boxed subtitle overlays.

STYLE BLOCK:
- Native IG Reels documentary-UGC energy: handheld feel, hard cuts on beats
- Generated B-roll: modern, clean, realistic — laptop/phone/packages/dashboard scenes; no cheesy stock-footage look, no watermarks
- Attached photos are the lifestyle payoff shots only (Scene 7)
- Keep the edit fast and clean; speech is the only required audio"""


async def main():
    t0 = time.time()
    url = await heygen.create_agent_video(
        prompt=PROMPT,
        avatar_id=PRIMARY_LOOK,
        voice_id=VOICE,
        orientation="portrait",
        files=FILES,
        timeout_s=1800,
    )
    out = {"code": "JH-AD-004", "video_url": url, "seconds": round(time.time() - t0)}
    with open("/tmp/jordan_ad4.json", "w") as f:
        json.dump(out, f)
    print(json.dumps(out))


try:
    asyncio.run(main())
except Exception as e:
    with open("/tmp/jordan_ad4.json", "w") as f:
        json.dump({"code": "JH-AD-004", "error": str(e)[:500]}, f)
    raise
