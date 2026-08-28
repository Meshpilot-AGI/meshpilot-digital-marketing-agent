"""JH-AD-005: "This should be illegal" forbidden-secret angle (Tejas-picked).
Different look (ref-5), dark conspiratorial treatment, scene-by-scene
storyboard, generated B-roll, single caption layer. Writes /tmp/jordan_ad5.json."""
import asyncio
import json
import os
import time

from meshpilot_creative.engines import heygen

VOICE = os.environ["JORDAN_HEYGEN_VOICE_ID"]
LOOK_REF5 = "e7342748b46c4539bf5adc735a0bcc33"  # different look from the group

PROMPT = """A 30-second vertical ad reel, dark and conspiratorial, built for instant clicks. High visual velocity: a new shot or visual change roughly every 2 seconds, zero dead air. The selected presenter is the narrator and anchor; GENERATE contextual B-roll between his lines — moody, modern automation imagery. Alternate presenter and B-roll constantly.

SCENE-BY-SCENE STORYBOARD (VO = voiceover; keep the Scene 1 line VERBATIM):

Scene 1 (0-1.5s) — PRESENTER very close to camera, lowered conspiratorial voice, like sharing a secret. VO: "What I'm about to show you should honestly be illegal." Text card slams: "THIS SHOULD BE ILLEGAL".
Scene 2 (~3s) — GENERATED B-ROLL: dark control-room aesthetic — a monitor wall of AI agent logs scrolling, an e-commerce dashboard filling with orders on its own. VO: "AI agents running an entire dropshipping store."
Scene 3 (~2s) — PRESENTER, counting on fingers, fast. VO: "Research. Listings. Orders. Customer service. No humans involved."
Scene 4 (~2s) — GENERATED B-ROLL: an empty desk chair in a dim office, notifications piling up on the screen behind it. No one there. VO continues.
Scene 5 (~3s) — PRESENTER, shakes head slightly. VO: "The unfair part? While everyone else grinds twelve-hour days... this thing runs itself."
Scene 6 (~2s) — GENERATED B-ROLL: split-mood contrast — exhausted person rubbing eyes at a laptop at 2am, hard cut to the same dashboard serenely processing orders.
Scene 7 (~4s) — PRESENTER leans in, beat of silence, quieter. VO: "And it gets worse. I'm not even real. I'm an AI the owner built with the same system — and I'm doing his marketing right now."
Scene 8 (~2s) — GENERATED B-ROLL: the presenter's frame freezes and a subtle digital wireframe/scanline pass sweeps over it, revealing the AI construction.
Scene 9 (~3s) — PRESENTER, direct, matter-of-fact. VO: "The whole setup is sixty-seven dollars. One time. Everything included."
Scene 10 (2s) — END CARD: near-black background, centered "buildaiempire.com" and "$67 one-time". VO: "Grab it before it gets taken down."

This storyboard is a concept to convey — not a rigid timeline. Refine pacing and shot details, but keep: the verbatim Scene 1 line, presenter/B-roll alternation, a visual change every ~2 seconds, and 30 seconds total.

Target duration: 30 seconds.

CRITICAL ON-SCREEN TEXT (render verbatim, do not rephrase):
- THIS SHOULD BE ILLEGAL
- buildaiempire.com
- $67 one-time

Tone: hushed, conspiratorial, slightly dangerous — sharing a secret that gives an unfair edge. Never cartoonish, never shouty.

CAPTION RULE (CRITICAL): EXACTLY ONE caption system — one styled kinetic caption layer synced to speech, clean white bold sans-serif, amber-yellow (#fbbf24) highlights on "illegal", "AI agents", "not even real", "$67". Do NOT add any second subtitle track, plain subtitle line, or boxed subtitle overlays.

STYLE BLOCK:
- Dark, moody grade: deep shadows, low-key lighting feel, amber accents — distinct from a bright UGC look
- Native IG Reels handheld energy, hard cuts on beats
- Generated B-roll: cinematic-dark modern tech imagery; realistic, no watermarks, no cheesy stock look
- Keep the edit fast and clean; speech is the only required audio"""


async def main():
    t0 = time.time()
    url = await heygen.create_agent_video(
        prompt=PROMPT,
        avatar_id=LOOK_REF5,
        voice_id=VOICE,
        orientation="portrait",
        timeout_s=1800,
    )
    out = {"code": "JH-AD-005", "video_url": url, "seconds": round(time.time() - t0)}
    with open("/tmp/jordan_ad5.json", "w") as f:
        json.dump(out, f)
    print(json.dumps(out))


try:
    asyncio.run(main())
except Exception as e:
    with open("/tmp/jordan_ad5.json", "w") as f:
        json.dump({"code": "JH-AD-005", "error": str(e)[:500]}, f)
    raise
