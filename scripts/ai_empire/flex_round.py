"""Flex round: 2 briefs (meta_proof, anti_guru) x (Hindi, English) = 4 videos,
each generated grounded (script_gen) then produced through the Video Agent
(persona_video), rotated looks, Agent's OWN b-roll (attach_broll=False)."""
import asyncio, os, sys, urllib.request
sys.path.insert(0, os.path.expanduser("~/glitch-grow-ads-agent-private/src"))
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/glitch-grow-ads-agent-private/.env"))
from meshpilot_creative import persona_video, script_gen

OUT = os.path.expanduser("~/india-persona/flex-round/videos"); os.makedirs(OUT, exist_ok=True)
BRAND, PERSONA = "ai-empire", "aanya"
BRIEF_IDS = ["meta_proof", "anti_guru"]


async def one(brief, lang, look):
    r = await script_gen.generate(BRAND, PERSONA, brief, lang)
    s = r["script"]
    text = f"{s.get('hook','')} {s.get('body','')} {s.get('cta','')}".strip()
    key = f"{brief['id']}-{'HI' if lang=='Hindi' else 'EN'}"
    print(f"START {key} look={look['id'][:8]} viol={r['violations']}", flush=True)
    url = await persona_video.produce(
        persona_id=PERSONA, script=text, look_id=look["id"], orientation="portrait",
        onscreen_text=["₹999", "buildaiempire.com"], duration_s=30,
        tone="confident, warm, direct", attach_broll=False)
    dest = f"{OUT}/aanya-{key}.mp4"; urllib.request.urlretrieve(url, dest)
    print(f"DONE {key} -> {os.path.getsize(dest)//1024} KB", flush=True)


async def main():
    briefs = {b["id"]: b for b in script_gen.load_briefs(BRAND)}
    looks = await persona_video.looks_for(PERSONA)
    tasks, i = [], 0
    for bid in BRIEF_IDS:
        for lang in ("Hindi", "English"):
            tasks.append(one(briefs[bid], lang, looks[i % len(looks)])); i += 1
    await asyncio.gather(*tasks)

asyncio.run(main())
