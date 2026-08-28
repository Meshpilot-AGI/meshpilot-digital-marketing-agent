"""Batch: 5 test-wave videos (JH-AD-006..010), each hook on its own look.
Serial renders; incremental results to /tmp/jordan_batch2.json."""
import asyncio
import json
import os
import time

from meshpilot_creative.engines import heygen

VOICE = os.environ["JORDAN_HEYGEN_VOICE_ID"]
LOOKS = json.load(open("/tmp/jordan_look_map.json"))
BROLL_BASE = "https://media.meshpilot.app/assets/jordan"

CAPTION_RULE = """CAPTION RULE (CRITICAL): EXACTLY ONE caption system — one styled kinetic caption layer synced to speech, clean white bold sans-serif, amber-yellow (#fbbf24) highlights on key words. Do NOT add any second subtitle track, plain subtitle line, or boxed subtitle overlays."""

COMMON = """This storyboard is a concept to convey — not a rigid timeline. Keep: the verbatim hook line, presenter/B-roll alternation, a visual change every ~2 seconds, 30 seconds total. Do not pad with silence.

Target duration: 30 seconds.

Tone: confident, conversational, zero hype — a practical friend talking. Native IG Reels handheld energy, hard cuts on beats. Generated B-roll: modern, clean, realistic; no watermarks, no cheesy stock look. Speech is the only required audio.

""" + CAPTION_RULE

SPECS = [
    {
        "code": "JH-AD-006", "look": "loft-window",
        "prompt": """A 30-second vertical curiosity reel. The selected presenter stands by a loft window, natural light.

SCENE-BY-SCENE (hook VERBATIM):
S1 (0-1.5s) PRESENTER close, genuinely puzzled energy. VO: "Why is nobody talking about this hack?" Text card: "NOBODY TALKS ABOUT THIS".
S2 (~3s) GENERATED B-ROLL: e-commerce dashboard running itself, orders ticking up, no one at the desk. VO: "AI agents running an entire store. Research, listings, orders, support."
S3 (~2s) PRESENTER, shrug. VO: "No team. No code."
S4 (~3s) GENERATED B-ROLL: split montage — AI chat writing a product listing / phone buzzing with sale notifications. VO: "It works while you sleep. Literally."
S5 (~4s) PRESENTER leans in. VO: "And the guy telling you this? Also AI. Built with the same $67 system."
S6 (~2s) GENERATED B-ROLL: subtle wireframe scanline sweep over the presenter frame.
S7 (~4s) PRESENTER, matter-of-fact. VO: "Every prompt, agent and pipeline is in the AI Empire Blueprint. Sixty-seven dollars. Once."
S8 (2s) END CARD: dark, "buildaiempire.com" + "$67 one-time". VO: "Now you know. Link below."

CRITICAL ON-SCREEN TEXT (verbatim): NOBODY TALKS ABOUT THIS / buildaiempire.com / $67 one-time

""",
    },
    {
        "code": "JH-AD-007", "look": "desk-office",
        "prompt": """A 30-second vertical story reel. The selected presenter sits at his home office desk.

SCENE-BY-SCENE (hook VERBATIM):
S1 (0-1.5s) PRESENTER direct, slight smile. VO: "Last year, I fired myself from my own business." Text card: "I FIRED MYSELF".
S2 (~3s) GENERATED B-ROLL: overwhelmed desk — sticky notes, endless inbox, late-night screen glow. VO: "I was the bottleneck. Every order, every customer email, every listing — me."
S3 (~3s) PRESENTER. VO: "So I replaced my whole job list with AI agents."
S4 (~3s) GENERATED B-ROLL: clean dashboard — agents handling research, listings, orders, support; tasks auto-completing. VO: "Research. Listings. Orders. Support. Gone."
S5 (~3s) PRESENTER relaxed, leaning back. VO: "Now I check in thirty minutes a day. Best firing I ever did."
S6 (~4s) PRESENTER, the twist. VO: "Oh — and the replacement for my marketing job? You're looking at him. I'm AI."
S7 (~3s) PRESENTER. VO: "The whole system is the AI Empire Blueprint. Sixty-seven dollars, one time."
S8 (2s) END CARD: dark, "buildaiempire.com" + "$67 one-time". VO: "Go fire yourself. Link below."

CRITICAL ON-SCREEN TEXT (verbatim): I FIRED MYSELF / buildaiempire.com / $67 one-time

""",
    },
    {
        "code": "JH-AD-008", "look": "whiteboard",
        "prompt": """A 30-second vertical teaching-rant reel. The selected presenter stands at a whiteboard, marker in hand.

SCENE-BY-SCENE (hook VERBATIM):
S1 (0-1.5s) PRESENTER pointing marker at camera. VO: "Gurus charge two thousand dollars to teach dropshipping in 2026. That's insane." Text card: "$2,000?? INSANE".
S2 (~3s) GENERATED B-ROLL: cliché guru imagery — rented lambo, course thumbnail wall, price tag $1,997 — quick X-out slashes over each. VO: "Forty-hour courses. Recycled theory. A payment plan."
S3 (~3s) PRESENTER counts on fingers at whiteboard. VO: "Meanwhile AI agents already do the work: research, listings, orders, support."
S4 (~3s) GENERATED B-ROLL: agents montage — dashboards, auto-written listings, order queue clearing itself.
S5 (~4s) PRESENTER taps whiteboard. VO: "The whole automated-store system — every prompt, agent and pipeline — is one sixty-seven dollar download."
S6 (~3s) PRESENTER half-grin, lean-in. VO: "And I'm AI, by the way. Even the sales pitch is automated."
S7 (~3s) PRESENTER. VO: "Sixty-seven. Not two thousand."
S8 (2s) END CARD: dark, "buildaiempire.com" + "$67 one-time". VO: "Class dismissed. Link below."

CRITICAL ON-SCREEN TEXT (verbatim): $67 NOT $2,000 / buildaiempire.com / $67 one-time

""",
    },
    {
        "code": "JH-AD-009", "look": "truck-ugc",
        "prompt": """A 30-second vertical raw UGC reel. The selected presenter sits in his parked truck, selfie-video framing, casual.

SCENE-BY-SCENE (hook VERBATIM):
S1 (0-1.5s) PRESENTER casual to camera. VO: "I can't code. My store doesn't care." Text card: "CAN'T CODE. DON'T CARE."
S2 (~3s) GENERATED B-ROLL: laptop on passenger seat, store dashboard processing orders on its own. VO: "AI agents run the whole thing from a laptop I barely open."
S3 (~2s) PRESENTER shrugs. VO: "Research? Agent. Listings? Agent. Customer service? Agent."
S4 (~3s) GENERATED B-ROLL: quick montage — AI writing listings, support replies sending, boxes at a doorstep.
S5 (~3s) PRESENTER. VO: "I even built my own software tool the same way. Still can't code."
S6 (~4s) PRESENTER, beat, deadpan. VO: "Also — I'm not real. The owner built me with the same system. Let that sink in."
S7 (~3s) PRESENTER. VO: "AI Empire Blueprint. Sixty-seven bucks, everything included."
S8 (2s) END CARD: dark, "buildaiempire.com" + "$67 one-time". VO: "Link below."

CRITICAL ON-SCREEN TEXT (verbatim): CAN'T CODE. DON'T CARE. / buildaiempire.com / $67 one-time

""",
    },
    {
        "code": "JH-AD-010", "look": "studio-podcast",
        "prompt": """A 30-second vertical full-meta reel. The selected presenter sits at a podcast desk, dark studio, amber accents — calm, confident, measured.

SCENE-BY-SCENE (hook VERBATIM):
S1 (0-2s) PRESENTER calm, direct into lens. VO: "Everything in this ad is AI. Including me." Text card: "THIS AD IS 100% AI".
S2 (~3s) GENERATED B-ROLL: elegant reveal — the presenter's frame decomposing into wireframe, then re-rendering photoreal. VO: "The face. The voice. The words."
S3 (~3s) PRESENTER. VO: "The same system runs a real store: research, listings, orders, support — all agents."
S4 (~3s) GENERATED B-ROLL: clean dashboards working, orders flowing, content queue publishing itself.
S5 (~3s) PRESENTER. VO: "It wrote this ad. It will post this ad. It tracks this ad."
S6 (~3s) PRESENTER slight smile. VO: "The machine is the proof. And the machine is for sale."
S7 (~4s) PRESENTER. VO: "AI Empire Blueprint. Every prompt, agent and pipeline. Sixty-seven dollars, one time."
S8 (2s) END CARD: dark, "buildaiempire.com" + "$67 one-time". VO: "Built by AI. Sold by AI. Link below."

CRITICAL ON-SCREEN TEXT (verbatim): THIS AD IS 100% AI / buildaiempire.com / $67 one-time

""",
    },
]


async def main():
    results = []
    for spec in SPECS:
        t0 = time.time()
        entry = {"code": spec["code"], "look": spec["look"]}
        try:
            url = await heygen.create_agent_video(
                prompt=spec["prompt"] + COMMON,
                avatar_id=LOOKS[spec["look"]],
                voice_id=VOICE,
                orientation="portrait",
                timeout_s=1800,
            )
            entry.update(video_url=url, seconds=round(time.time() - t0))
        except Exception as e:
            entry["error"] = str(e)[:300]
        results.append(entry)
        json.dump(results, open("/tmp/jordan_batch2.json", "w"), indent=1)
        print(entry.get("code"), "->", "OK" if "video_url" in entry else entry.get("error", "?")[:80])
    print("BATCH DONE", sum(1 for r in results if "video_url" in r), "/", len(SPECS))


asyncio.run(main())
