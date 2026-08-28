"""Seed Aanya's 15 photos into the pipeline content_plan, then post via the
pipeline's own posting_tick (NOT a bespoke poster). Token resolved from the store.
  python seed_and_post.py seed
  python seed_and_post.py post 1
  python seed_and_post.py post 14
"""
import asyncio, os, re, sys
REPO = os.path.expanduser("~/glitch-grow-ads-agent-private")
sys.path.insert(0, REPO + "/src"); sys.path.insert(0, REPO + "/src/social_agent/src")
from dotenv import load_dotenv
load_dotenv(REPO + "/.env")
load_dotenv(REPO + "/.env.influencer-secrets", override=True)
if not os.environ.get("POSTGRES_BRAIN_URL"):
    m = re.search(r'postgres(?:ql)?://[^\s"]+glitch_brain[^\s"]*', open(REPO + "/.env").read())
    if m: os.environ["POSTGRES_BRAIN_URL"] = m.group(0)
from glitch_signal.influencer import content_plan, pipeline
from meshpilot_creative.engines import muapi_cli

FEED = os.path.expanduser("~/india-persona/feed")
ORDER = ["aanya-01-portrait-warm","aanya-02-home-desk","aanya-03-cafe-window","aanya-04-balcony-golden",
 "aanya-05-city-walk","aanya-06-sofa-evening","aanya-07-presenting","aanya-08-coffee-morning",
 "aanya-09-blazer-portrait","aanya-10-flatlay-hands","aanya-11-rooftop-evening","aanya-12-reading-weekend",
 "aanya-13-coworking","aanya-14-phone-candid","aanya-15-park-laptop"]
CAP = {
 "aanya-01-portrait-warm":"Hi, main Aanya. Pune se. Apna online business AI se chalati hoon - aur haan, main khud bhi AI hoon. Yahan sirf honest baat: AI se kaam kaise hota hai, bina hype.\n#AIbusiness #sideincome",
 "aanya-02-home-desk":"45 minutes a day. Bas itna. AI store banata hai, content likhta hai, main sirf direct karti hoon. Ghar baithe, apne terms pe.\n#ghartbaithebusiness #makemoneywithAI",
 "aanya-03-cafe-window":"Coffee, laptop, aur ek system jo background me chalta rahe. Naya India aise dikhta hai.\n#financialfreedom #AIsidehustle",
 "aanya-04-balcony-golden":"Golden hour. Business chal raha hai, main saans le rahi hoon. Koi guru nahi - ek system.\n#buildinpublic #automation",
 "aanya-05-city-walk":"Nau-se-paanch waali life nahi chahiye thi. Toh AI ke saath apni bana li.\n#quitthe9to5 #womeninbusiness",
 "aanya-06-sofa-evening":"Raat ke 9 baje, koi office email nahi. AI ne mera time wapas de diya.\n#automation #worklifebalance",
 "aanya-07-presenting":"Log poochte hain - AI se paisa kaise? Toh main dikhati hoon, asli aur step by step, bina hype.\n#makemoneywithAI #honest",
 "aanya-08-coffee-morning":"Subah ki coffee is better than subah ke deadlines. System chalta rahe, main jeeti rahun.\n#morningroutine #freedom",
 "aanya-09-blazer-portrait":"Apna boss banne ke liye degree nahi, ek system chahiye. Aur thodi si himmat.\n#womenandmoney #entrepreneur",
 "aanya-10-flatlay-hands":"Aaj ka office: laptop, ek notebook, aur ek AI jo bhaari kaam sambhalta hai.\n#digitalbusiness #ghartbaithe",
 "aanya-11-rooftop-evening":"Sheher ki lights, aur ek business jo mujh pe depend nahi karta. Ye freedom kharidi nahi, banayi.\n#buildinpublic #AItools",
 "aanya-12-reading-weekend":"Weekend matlab weekend. Kaam AI ne kar diya.\n#automation #worklifebalance",
 "aanya-13-coworking":"Confidence tab aata hai jab pata ho system chal raha hai.\n#womeninbusiness #AItools",
 "aanya-14-phone-candid":"Roz DM aati hai - didi, kaise shuru karun? Toh yahan sab kuch share karti hoon, free. (Main ek AI creator hoon.)\n#makemoneyonlineindia",
 "aanya-15-park-laptop":"Office kahin bhi ho sakta hai jab AI heavy lifting kare. Aaj: ye bench. Kal: kahin aur.\n#laptoplifestyle #freedom",
}

async def seed():
    for name in ORDER:
        url = await muapi_cli.upload(f"{FEED}/{name}.jpg")
        pid = await content_plan.add_idea("ai-empire", "aanya", discovery_source="operator_seed",
                                          format="image", platform="instagram", pillar="the_999_blueprint")
        await content_plan.write_back(pid, {"status": "ready", "asset_url": url,
                                            "format": "image", "platform": "instagram", "caption": CAP[name]})
        print("seeded", name, "plan", pid)

async def post(n):
    for i in range(n):
        r = await pipeline.posting_tick("ai-empire", persona_id="aanya")
        print(f"[{i+1}] {r.status}: plan={getattr(r,'plan_id',None)} {getattr(r,'detail','')}")
        if r.status not in ("posted",):
            print("   (stopping loop — not posted)"); break
        await asyncio.sleep(35)

async def reready():
    rows = await content_plan.fetch_rows("ai-empire", status="failed", persona="aanya")
    for r in rows:
        await content_plan.write_back(r.id, {"status": "ready"})
    print("re-readied failed rows:", len(rows))

mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
if mode == "seed":
    asyncio.run(seed())
elif mode == "reready":
    asyncio.run(reready())
else:
    asyncio.run(post(int(sys.argv[2]) if len(sys.argv) > 2 else 1))
