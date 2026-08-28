"""JH-AD-001 v2: Jordan founder-yapper talking head via Avatar IV
(photo avatars don't run on Video Agent). Burned captions on, 9:16, 1080p.
Writes result JSON to /tmp/jordan_ad1.json.
"""
import asyncio
import json
import os
import time

from meshpilot_creative.engines import heygen

GROUP = os.environ["JORDAN_HEYGEN_GROUP_ID"]
VOICE = os.environ["JORDAN_HEYGEN_VOICE_ID"]

SCRIPT = (
    "I automated my business with AI agents. Then I built my own software tools. "
    "And I still can't code. "
    "My dropshipping operation runs on agents now. Research, listings, orders, "
    "customer support. The boring half handles itself. "
    "The same method built me a full trading tool, without writing production code. "
    "And here's the part people don't believe. The face you're watching right now? "
    "AI too. I'm the distribution layer, and I run on the same system. "
    "Once it's set up, it's thirty to forty-five minutes a day. "
    "Every prompt, agent template and pipeline is in the AI Empire Blueprint. "
    "Sixty-seven dollars, one time. Build AI empire dot com."
)

MOTION = (
    "Subtle natural head movement and hand gestures, direct eye contact with camera, "
    "confident casual founder energy, slight lean-in on key lines, authentic and "
    "conversational, no exaggerated motion"
)


async def main():
    t0 = time.time()
    look = await heygen.resolve_look(GROUP, "portrait")
    url = await heygen.avatar_iv_video(
        avatar_look_id=look["id"],
        script=SCRIPT,
        voice_id=VOICE,
        aspect_ratio="9:16",
        motion_prompt=MOTION,
        expressiveness="medium",
        caption=True,
        resolution="1080p",
        title="JH-AD-001 founder-yapper",
        timeout_s=1800,
    )
    out = {
        "code": "JH-AD-001",
        "video_url": url,
        "look_id": look["id"],
        "seconds": round(time.time() - t0),
    }
    with open("/tmp/jordan_ad1.json", "w") as f:
        json.dump(out, f)
    print(json.dumps(out))


try:
    asyncio.run(main())
except Exception as e:
    with open("/tmp/jordan_ad1.json", "w") as f:
        json.dump({"code": "JH-AD-001", "error": str(e)[:500]}, f)
    raise
