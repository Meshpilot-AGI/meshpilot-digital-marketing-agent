"""JH-AD-002: Video Agent attempt with Jordan's primary LOOK id, deep
producer prompt (full heygen-video skill guardrails), luxury B-roll files.
Writes /tmp/jordan_ad2.json. Falls back with a clear error if Video Agent
rejects photo-avatar looks."""
import asyncio
import json
import os
import time

from meshpilot_creative.engines import heygen

VOICE = os.environ["JORDAN_HEYGEN_VOICE_ID"]
PRIMARY_LOOK = "b4012e41fa0d4b60996d0800a7345a30"  # locked-face primary

BROLL_BASE = "https://1c76c506.ai-empire-blueprint.pages.dev/jordan"
BROLL = [
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-lakehouse-deck.jpg"},
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-home-deck.jpg"},
    {"type": "url", "url": f"{BROLL_BASE}/jordan-luxury-home-patio.jpg"},
]

PROMPT = """The selected presenter delivers a raw, direct-to-camera founder reel. One topic only: how he automated his business with AI agents and now sells the exact system.

SCRIPT (concept and beats):
Opening hook, tight on presenter, high energy first line: "I automated my business with AI agents. Then I built my own software tools. And I still can't code."
Beat 2 — the machine: his dropshipping operation runs on agents now: research, listings, orders, customer support. The boring half of the business handles itself.
Beat 3 — the proof escalates: the same orchestration method built him a full trading tool without writing production code.
Beat 4 — the twist, presenter leans in, slight pause before the reveal: "The face you're watching right now? AI too. I'm the distribution layer, and I run on the same system."
Beat 5 — grounding: once it's set up, it runs on thirty to forty-five minutes a day.
Close — CTA: every prompt, agent template and pipeline is in the AI Empire Blueprint. Sixty-seven dollars, one time. Build AI empire dot com.

This script is a concept and theme to convey — not a verbatim transcript. You have full creative freedom to expand, elaborate, add examples, and fill the duration naturally. Do not pad with silence or pauses.

Target duration: about 45 seconds.

CRITICAL ON-SCREEN TEXT (render verbatim, do not rephrase):
- buildaiempire.com
- $67 one-time

B-ROLL ANCHORING: Use the three attached lifestyle photos as brief cutaway B-roll ONLY during Beat 5 (the freedom/results beat) and under the closing CTA — quick cuts, 1-2 seconds each, with subtle slow push-in motion. Do NOT generate stock footage; the attached photos are the only B-roll. At least 70% of the runtime stays on the presenter talking.

Tone: confident, conversational, zero hype — a practical friend explaining his setup. Slightly amused at the AI reveal, never salesy.

STYLE BLOCK:
- Native Instagram Reels energy: raw founder-yapper, handheld feel, quick punchy cuts on beat changes
- Kinetic bold caption text synced to speech, high contrast, amber-yellow accent color (#fbbf24) on key words: "AI agents", "can't code", "AI too", "$67"
- On-screen text and captions in English; clean sans-serif
- Hook text card in the first 1.5 seconds mirroring the first line
- No corporate polish, no music bed louder than speech, subtle trending-reel pacing
- End card: dark background, "AI EMPIRE BLUEPRINT" wordmark feel, buildaiempire.com + $67 one-time centered"""


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
    out = {"code": "JH-AD-002", "video_url": url, "seconds": round(time.time() - t0)}
    with open("/tmp/jordan_ad2.json", "w") as f:
        json.dump(out, f)
    print(json.dumps(out))


try:
    asyncio.run(main())
except Exception as e:
    with open("/tmp/jordan_ad2.json", "w") as f:
        json.dump({"code": "JH-AD-002", "error": str(e)[:500]}, f)
    raise
