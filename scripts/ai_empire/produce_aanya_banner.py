"""Aanya website video banner — YouTube-style LANDSCAPE HeyGen Video Agent video
(same path as Jordan's), via the persona_video system. Grounded reveal/intro script."""
import asyncio, os, re, sys, urllib.request
REPO = os.path.expanduser("~/glitch-grow-ads-agent-private")
sys.path.insert(0, REPO + "/src"); sys.path.insert(0, REPO + "/src/social_agent/src")
from dotenv import load_dotenv
load_dotenv(REPO + "/.env"); load_dotenv(REPO + "/.env.influencer-secrets", override=False)
from meshpilot_creative import persona_video, script_gen

OUT = os.path.expanduser("~/india-persona/banner"); os.makedirs(OUT, exist_ok=True)

async def main():
    briefs = {b["id"]: b for b in script_gen.load_briefs("ai-empire")}
    r = await script_gen.generate("ai-empire", "aanya", briefs["meta_proof"], "English")
    s = r["script"]
    text = f"{s.get('hook','')} {s.get('body','')} {s.get('cta','')}".strip()
    print("SCRIPT:", text)
    print("violations:", r["violations"])
    url = await persona_video.produce(
        persona_id="aanya", script=text, orientation="landscape",
        onscreen_text=["₹999", "buildaiempire.com"], duration_s=45,
        tone="confident, warm, direct — a YouTube explainer intro", attach_broll=False)
    dest = f"{OUT}/aanya-website-banner.mp4"
    urllib.request.urlretrieve(url, dest)
    print("SAVED", dest, os.path.getsize(dest) // 1024, "KB")

asyncio.run(main())
