"""Cinematic 9:16 ad backgrounds for Aanya (muapi nano-banana, identity-locked),
mirroring Jordan's ads-static bases: amber-lit, negative space at the bottom for text."""
import asyncio, os, sys, json, urllib.request
sys.path.insert(0, os.path.expanduser("~/glitch-grow-ads-agent-private/src"))
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/glitch-grow-ads-agent-private/.env"))
from meshpilot_creative.engines import muapi as M

HU = json.load(open(os.path.expanduser("~/india-persona/hosted_urls.json")))
REFS = [HU["locked"], HU["ref1-hero-amber"], HU["ref6-three-quarter"]]
OUT = os.path.expanduser("~/india-persona/flex-round/images/bg"); os.makedirs(OUT, exist_ok=True)

ID = ("the exact same woman as in ALL reference images, identical face, identical shoulder-length "
      "dark wavy hair, identical eyes and facial structure, 27 year old confident Indian woman, "
      "warm direct expression, ")
RECIPE = (", shot on 85mm lens, shallow depth of field, soft natural skin texture with visible pores, "
          "no airbrushing, photoreal, subtle film grain, cinematic dramatic lighting, dslr, no makeup")

SCENES = {
 "wire": "editorial half-body portrait, the left side of her face, shoulder and arm dissolve into glowing amber digital wireframe mesh and drifting particles, right side photoreal, dark charcoal background, dramatic amber rim light, lots of empty dark space at the bottom for text overlay",
 "desk": "sitting at a modern desk at night, a laptop open showing a glowing amber automation dashboard with a node diagram and charts, warm screen glow on her face, focused capable expression, dark moody room, lots of empty dark space at the bottom for text overlay",
 "wall": "half-body standing against a charcoal studio wall, editorial key light with soft amber rim light, modern well-fitted blazer, arms relaxed, calm confident, lots of empty dark space at the bottom and side for text overlay",
 "cafe": "relaxed and confident at a modern cafe by a window at golden hour holding a coffee cup, warm cinematic light, dark moody tones, lots of empty dark space at the bottom for text overlay",
 "present": "standing, talking to camera mid-explanation with a natural hand gesture, confident and animated, dark backdrop with a subtle amber glow, lots of empty dark space at the bottom for text overlay",
}

async def gen(name, scene):
    try:
        url = await M.generate("nano-banana", ID + scene + RECIPE, images=REFS,
                               settings_overrides={"aspect_ratio": "9:16"})
        dest = f"{OUT}/{name}.jpg"; urllib.request.urlretrieve(url, dest)
        print("OK", name, os.path.getsize(dest) // 1024, "KB", flush=True)
    except Exception as e:
        print("FAIL", name, type(e).__name__, str(e)[:160], flush=True)

async def main():
    await asyncio.gather(*(gen(n, s) for n, s in SCENES.items()))

asyncio.run(main())
