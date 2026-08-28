"""Round 1 Aanya videos via the canonical persona_video system (HeyGen Video
Agent), rotating a DIFFERENT look per video across her avatar group.

Usage:
  python round01_aanya_agent_videos.py           # produce all 6
  python round01_aanya_agent_videos.py 5         # produce only index 5 (test)
"""
import asyncio
import os
import sys
import urllib.request

sys.path.insert(0, os.path.expanduser("~/glitch-grow-ads-agent-private/src"))
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/glitch-grow-ads-agent-private/.env"))
from meshpilot_creative import persona_video

OUT = os.path.expanduser("~/india-persona/round01-agent")
os.makedirs(OUT, exist_ok=True)

CTA = ["₹999", "buildaiempire.com"]  # verbatim on-screen (price + URL)

# (key, script) — number words so TTS says them right.
VIDEOS = [
 ("A-outcome-HI", "AI use karke ghar baithe chalis hazaar mahina — sirf pentaalis minute kaam. Kaise? Main dikhati hoon. Ye koi guru course nahi. Ek real online business — ads, content, website, sab AI chalata hai. Ghar baithe, bina coding, bina team. Maine ek baar system set kiya. Ab AI ads banata hai, content post karta hai, customers ko reply karta hai. Main sirf pentaalis minute check karti hoon. Aur sach? Main khud AI hoon — ye chehra, ye awaaz, isi system se bana. Koi guaranteed paisa nahi — ye system hai, jaadu nahi. Poora system sirf nau sau ninyaanve rupaye mein. buildaiempire dot com pe abhi shuru karo."),
 ("A-outcome-EN", "Forty thousand rupees a month on the side. Forty five minutes a day. Run by AI. Here is how. Not a guru course. A real online business — ads, content, website — all run by AI. From home, no code, no team. I set the system up once. Now AI runs the ads, posts content, replies to customers. I just check in for forty five minutes. And the truth? I am AI too — this face, this voice, built by the same system. No guaranteed income — it is a system, not magic. The whole system, nine hundred and ninety nine rupees. Start today at buildaiempire dot com."),
 ("B-starttoday-HI", "Ajj hi apna online business shuru karo — bina coding, bina team, sirf AI ke saath. Ghar baithe side income — jahan AI tumhare liye ads, content aur website sab sambhalta hai. System ek baar set karo, AI baaki sab karta hai — roz sirf pentaalis minute tumhare. Main bhi isi system se bani hoon — haan, main AI hoon. Business real, method real, koi income guarantee nahi. Nau sau ninyaanve rupaye mein poora blueprint. buildaiempire dot com — ajj se shuru."),
 ("B-starttoday-EN", "Start your own online business today. No code, no team — just AI. A side income from home, where AI handles the ads, the content and the website for you. Set the system up once, AI does the rest — forty five minutes a day is yours. I was built by this system too — yes, I am AI. The business is real, the method is real, no income guarantee. The full blueprint, nine hundred and ninety nine rupees. Start today at buildaiempire dot com."),
 ("C-reveal-HI", "Ye ladki real nahi hai. Na ye awaaz. Par jo business ye chalati hai — wo bilkul real hai. Ek automated online business — AI ads, content aur website sab chalata hai. Ghar baithe side income. Main isi AI Empire system se bani — aur isi system se ye business roz pentaalis minute mein chalta hai. Sab disclosed hai — main AI hoon. Agar AI mujhe bana sakti hai, socho tumhare liye kya bana sakti hai. Koi guarantee nahi, ek system. Nau sau ninyaanve rupaye. buildaiempire dot com pe abhi."),
 ("C-reveal-EN", "This creator is not real. Her voice is not either. The business she runs? Completely real. An automated online business — AI runs the ads, content and website. A side income from home. I was built by the AI Empire system — and the same system runs this business in forty five minutes a day. It is all disclosed — I am AI. If AI can build me, imagine what it builds for you. No guarantee, just a system. Nine hundred and ninety nine rupees. buildaiempire dot com."),
]


async def one(i, key, script, look):
    tag = " MOTION" if look["is_motion"] else ""
    print(f"[{i}] START {key} look={look['name']}:{look['id'][:8]}{tag}", flush=True)
    try:
        url = await persona_video.produce(
            persona_id="aanya", script=script, look_id=look["id"],
            orientation="portrait", onscreen_text=CTA, duration_s=30,
            tone="confident, warm, direct, anti-guru")
        dest = f"{OUT}/aanya-agent-{key}.mp4"
        urllib.request.urlretrieve(url, dest)
        print(f"[{i}] DONE {key} -> {os.path.getsize(dest)//1024} KB", flush=True)
    except Exception as e:
        print(f"[{i}] FAIL {key} {type(e).__name__}: {str(e)[:220]}", flush=True)


async def main():
    looks = await persona_video.looks_for("aanya")
    print("group looks:", [f"{l['name']}{'/M' if l['is_motion'] else ''}:{l['id'][:8]}" for l in looks], flush=True)
    only = int(sys.argv[1]) if len(sys.argv) > 1 else None
    tasks = [one(i, key, script, looks[i % len(looks)])
             for i, (key, script) in enumerate(VIDEOS) if only is None or i == only]
    await asyncio.gather(*tasks)

asyncio.run(main())
