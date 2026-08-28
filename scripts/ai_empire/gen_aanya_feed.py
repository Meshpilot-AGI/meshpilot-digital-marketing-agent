"""15 on-brand Instagram feed photos of Aanya (muapi nano-banana, identity-locked)
- varied lifestyle/portrait scenes for a fresh @aanya.jain.ai grid. 1:1."""
import asyncio, os, sys, json, urllib.request
sys.path.insert(0, os.path.expanduser("~/glitch-grow-ads-agent-private/src"))
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/glitch-grow-ads-agent-private/.env"))
from meshpilot_creative.engines import muapi as M

HU = json.load(open(os.path.expanduser("~/india-persona/hosted_urls.json")))
REFS = [HU["locked"], HU["ref1-hero-amber"], HU["ref6-three-quarter"]]
OUT = os.path.expanduser("~/india-persona/feed"); os.makedirs(OUT, exist_ok=True)

ID = ("the exact same woman as in ALL reference images, identical face, identical shoulder-length dark "
      "wavy hair, identical eyes and facial structure, 27 year old confident Indian woman, warm direct "
      "expression, ")
RECIPE = (", shot on 85mm lens, shallow depth of field, soft natural skin texture with visible pores, no "
          "airbrushing, photoreal, natural lighting, subtle film grain, dslr, no makeup, authentic candid")

SCENES = {
 "01-portrait-warm": "clean chest-up portrait, warm soft studio light, dark background, calm confident slight smile, looking at camera",
 "02-home-desk": "sitting at a modern home desk in the morning, laptop open and a coffee mug, focused capable expression, bright airy room",
 "03-cafe-window": "relaxed at a bright modern cafe by a window holding a coffee cup, natural daylight, casual stylish outfit, warm approachable smile",
 "04-balcony-golden": "on a modern apartment balcony at golden hour, phone in hand, calm satisfied expression, warm sunlight and a few plants",
 "05-city-walk": "walking a clean modern city street in smart-casual clothes, candid, natural daylight, soft smile",
 "06-sofa-evening": "cozy on a sofa at home in the evening with a laptop, warm lamp light, relaxed",
 "07-presenting": "talking to the camera mid-explanation with a natural hand gesture, content-creator vibe, soft key light, plain modern background",
 "08-coffee-morning": "morning coffee by a large window, soft natural light, calm, wrapped in a light cardigan",
 "09-blazer-portrait": "confident three-quarter portrait in a modern well-fitted blazer against a clean neutral wall, soft light",
 "10-flatlay-hands": "top-down view of her hands typing on a laptop with a notebook, pen and coffee on a clean desk, warm daylight",
 "11-rooftop-evening": "at a rooftop cafe in the evening with soft city bokeh lights behind her, smiling, cozy",
 "12-reading-weekend": "relaxed reading on a tablet on a lazy weekend morning at home, soft natural light, cozy",
 "13-coworking": "standing in a bright modern coworking space, arms lightly crossed, confident, blurred desks behind",
 "14-phone-candid": "candid closer shot holding up her phone showing content, natural indoor light, genuine smile",
 "15-park-laptop": "sitting on a park bench at golden hour with a laptop, aspirational and calm, warm light and greenery",
}

async def gen(name, scene):
    try:
        url = await M.generate("nano-banana", ID + scene + RECIPE, images=REFS,
                               settings_overrides={"aspect_ratio": "1:1"})
        dest = f"{OUT}/aanya-{name}.jpg"; urllib.request.urlretrieve(url, dest)
        print("OK", name, os.path.getsize(dest) // 1024, "KB", flush=True)
    except Exception as e:
        print("FAIL", name, type(e).__name__, str(e)[:120], flush=True)

async def main():
    items = list(SCENES.items())
    for i in range(0, len(items), 5):
        await asyncio.gather(*(gen(n, s) for n, s in items[i:i+5]))

asyncio.run(main())
