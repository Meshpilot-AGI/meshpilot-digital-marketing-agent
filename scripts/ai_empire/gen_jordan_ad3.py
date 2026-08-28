"""JH-AD-003b (effects/music stripped — isolating Video Agent failure): 30s click-optimized founder reel. $2,000-day hook (Tejas-approved
script), single caption system (fixes AD-002's double subtitles).
Writes /tmp/jordan_ad3.json."""
import asyncio
import json
import os
import time

from meshpilot_creative.engines import heygen

VOICE = os.environ["JORDAN_HEYGEN_VOICE_ID"]
PRIMARY_LOOK = "b4012e41fa0d4b60996d0800a7345a30"

BROLL_BASE = "https://1c76c506.ai-empire-blueprint.pages.dev/jordan"
BROLL = [
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-lakehouse-deck.jpg"},
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-home-patio.jpg"},
]

PROMPT = """The selected presenter delivers a fast, direct-to-camera founder reel built for instant clicks. One topic: the AI hack running his dropshipping store.

SCRIPT (concept and beats — approved copy, keep the hook line VERBATIM):
HOOK (0-1.5s, presenter tight to camera, matching bold text card): "I used this hack to hit a $2,000 sales day on my dropshipping store."
Beat 2 (rapid-fire): "No team. And I can't even code. AI agents run the whole thing — they find the products, write the listings, process the orders, answer the customers."
Beat 3 (settle, half-smile): "I check in for thirty minutes a day. That's it."
Beat 4 (the twist, lean-in, beat of silence before it): "And the crazy part? The guy telling you this is AI too. Built with the same system."
CTA (urgent but friendly): "It's called the AI Empire Blueprint. Sixty-seven bucks, one time, everything included. Grab it while it's still $67 — link below."

This script is a concept and theme to convey — not a verbatim transcript (EXCEPT the hook line, which must be spoken exactly as written). Expand naturally but stay tight. Do not pad with silence.

Target duration: 30 seconds maximum. Keep it punchy — every second earns the next.

CRITICAL ON-SCREEN TEXT (render verbatim, do not rephrase):
- $2,000 SALES DAY
- buildaiempire.com
- $67 one-time

B-ROLL ANCHORING: The two attached lifestyle photos are the ONLY B-roll. Use them as quick 1-second push-in cutaways: one on the "thirty minutes a day" beat, one under the CTA. Never during the hook or the twist. At least 80% of runtime on the presenter.

Tone: urgent, confident, slightly conspiratorial — like telling a friend something before it stops working. Zero corporate polish.

CAPTION RULE (CRITICAL): Use EXACTLY ONE caption system — a single styled kinetic caption layer synced to speech: clean white bold sans-serif with amber-yellow (#fbbf24) highlights on money words ("$2,000", "AI agents", "AI too", "$67"). Do NOT add any second subtitle track, plain white subtitle line, or boxed subtitle overlays. One text layer for captions, nothing else, ever.

STYLE BLOCK:
- Native IG Reels, raw handheld founder energy, hard cuts SLAM on beat changes
- Hook text card in first second: "$2,000 SALES DAY" — big, bold, amber on dark
- End card (last 2s): dark background, buildaiempire.com and $67 one-time centered, nothing else
- Keep the edit clean and fast; speech is the only required audio"""


async def main():
    t0 = time.time()
    url = await heygen.create_agent_video(
        prompt=PROMPT,
        avatar_id=PRIMARY_LOOK,
        voice_id=VOICE,
        orientation="portrait",
        files=BROLL,
        timeout_s=1800,
    )
    out = {"code": "JH-AD-003", "video_url": url, "seconds": round(time.time() - t0)}
    with open("/tmp/jordan_ad3.json", "w") as f:
        json.dump(out, f)
    print(json.dumps(out))


try:
    asyncio.run(main())
except Exception as e:
    with open("/tmp/jordan_ad3.json", "w") as f:
        json.dump({"code": "JH-AD-003", "error": str(e)[:500]}, f)
    raise
