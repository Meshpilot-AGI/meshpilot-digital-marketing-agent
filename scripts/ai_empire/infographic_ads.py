"""Neon-infographic ad images for AI Empire personas (gpt-image-2).

Matches the reference ad style (glowing feature cards, dashboard mockups,
condensed headlines, amber pill CTAs). gpt-image-2 renders the crisp text + neon
design that a photo-overlay compositor cannot. Persona face is passed as a ref
for the person/reveal layouts (identity holds).

Compliance (enforced by the prompts): NO income/sales figures; the dashboard
shows ORDERS not revenue; the AI disclosure appears on person-facing ads. Only
the ₹999 price and the ₹50,000 guru-course contrast are shown as money.

CLI:  python src/social_agent/scripts/ai_empire/infographic_ads.py [id ...]
      (no args = all). Output -> ~/india-persona/flex-round/images/infographic/<id>.jpg
"""
import asyncio, os, sys, json, urllib.request
sys.path.insert(0, os.path.expanduser("~/glitch-grow-ads-agent-private/src"))
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/glitch-grow-ads-agent-private/.env"))
from meshpilot_creative.engines import muapi as M

REFS = os.path.expanduser("~/india-persona/hosted_urls.json")  # persona face refs
OUT = os.path.expanduser("~/india-persona/flex-round/images/infographic")
os.makedirs(OUT, exist_ok=True)

# id -> (prompt, needs_face)
ADS = {
 "ig-01-featurelist": ((
   "Bold high-energy square marketing graphic, pure black background with a subtle warm amber glow along "
   "the edges. LEFT HALF: a large stacked headline in capitals - a small 'THE' on top, then a giant glowing "
   "golden-amber price 'Rs 999' with a strong neon glow, then 'AI BUSINESS SYSTEM' in heavy white condensed "
   "bold below. Under it two lines of white text: 'AI agents run the ads, the socials and the website. You "
   "check in 45 minutes a day.' Below that a large glowing amber rounded pill button with black bold "
   "uppercase text 'GET THE BLUEPRINT'. At the very bottom small white text: 'one zip. Rs 999, once. 7 day "
   "guarantee.' RIGHT HALF: a vertical stack of six dark rounded cards, each with a glowing amber neon "
   "border, a glowing amber thin line icon and a bold white label with a small grey sub-label: "
   "'ADS / writes and tests creatives', 'SOCIAL / posts every day', 'WEBSITE / writes itself', "
   "'AI INFLUENCER / your brand face', 'SUPPORT / replies drafted', 'DELIVERY / instant to buyers'; the "
   "cards connected by a glowing amber vertical circuit line with small nodes. Premium modern neon "
   "infographic, crisp perfectly legible text, high contrast."), False),

 "ig-02-person": ((
   "Bold square marketing graphic, near-black background. TOP: headline 'COPY MY' in white bold caps, then "
   "'AI-RUN BUSINESS' in glowing amber bold caps with a thin amber underline, then a grey subline 'every job "
   "handled by AI agents'. CENTER: the SAME confident young Indian woman as the reference image, identical "
   "face, shoulder-length dark wavy hair, wearing a dark top, arms crossed, cut out on the dark background "
   "with a warm amber rim light. Around her four floating dark rounded chips with glowing amber neon borders, "
   "each a white line icon and white label: top-left 'AI ADS', top-right 'AI SOCIAL', bottom-left "
   "'AI WEBSITE', bottom-right 'AI INFLUENCER'. BOTTOM: a glowing amber rounded pill with white bold text "
   "'GET THE BLUEPRINT - Rs 999', and below small white text 'one time. no subscription.'. Premium modern "
   "neon infographic, crisp perfectly legible text."), True),

 "ig-03-dashboard": ((
   "Bold square marketing graphic, pure black background. TOP HALF: a realistic dark analytics dashboard on "
   "a floating tablet titled 'Business Overview', showing an Orders count, a small line chart labeled Orders "
   "Over Time, a channel breakdown donut, a 'Recent Activity' table listing recent completed orders with "
   "customer first names and sales channels, and a 'Top Products' list. Clean modern dark fintech UI with "
   "subtle amber accents. IMPORTANT: do NOT show any large total-revenue money amount. Around the tablet "
   "four floating neon callout labels with thin arrows pointing at it, each a different neon color: 'ADS "
   "AGENT' amber, 'SOCIAL AGENT' purple, 'SITE AGENT' blue, 'SUPPORT AGENT' green. BOTTOM HALF: a huge white "
   "bold condensed headline 'THE WHOLE BUSINESS, RUN BY AGENTS.' then a giant glowing amber 'Rs 999' with the "
   "small white word 'once.' beside it, then white text '7 day money back. Or you do not pay.' and a row of "
   "three white line icons labeled 'one zip', '6 agents', 'your store'. Premium neon infographic, crisp "
   "perfectly legible text."), False),

 "ig-04-compare": ((
   "Bold square marketing graphic, pure black background with a subtle amber edge glow. TOP: white bold "
   "condensed headline 'STOP BUYING Rs 50,000 COURSES'. Below it two side-by-side comparison cards. LEFT card "
   "has a red neon border and a red X mark, title 'Rs 50,000 GURU COURSE' and three white bullet lines: 'just "
   "theory', 'no real system', 'still on your own'. RIGHT card has a glowing amber neon border and an amber "
   "check mark, title 'THE Rs 999 SYSTEM' and three white bullet lines: 'the actual working setup', 'six AI "
   "agents included', 'yours forever, no subscription'. BOTTOM: a glowing amber rounded pill with black bold "
   "uppercase text 'GET THE BLUEPRINT - Rs 999' and small white text below 'one time. 7 day money back.'. "
   "Premium modern neon infographic, crisp perfectly legible text, high contrast."), False),

 "ig-05-reveal": ((
   "Bold square marketing graphic, near-black background with subtle glowing amber digital particles. On the "
   "RIGHT, the SAME confident young Indian woman as the reference image, identical face, shoulder-length dark "
   "wavy hair, wearing a dark top, warm amber rim light, a few glowing amber wireframe particles drifting off "
   "her shoulder. On the LEFT, a huge white bold condensed headline 'EVEN I'M AI.' then below it in glowing "
   "amber bold 'SO IS THIS BUSINESS.', then a grey subline 'this face, this ad, the store - all built by the "
   "same system'. BOTTOM LEFT: a glowing amber rounded pill with black bold text 'GET THE BLUEPRINT - Rs "
   "999', and small grey text below 'Aanya is an AI-generated creator'. Premium neon infographic, crisp "
   "legible text."), True),
}


async def gen(ad_id, prompt, needs_face, face_refs):
    try:
        images = face_refs if needs_face else []
        url = await M.generate("gpt-image-2", prompt, images=images,
                               settings_overrides={"aspect_ratio": "1:1"})
        dest = f"{OUT}/{ad_id}.jpg"; urllib.request.urlretrieve(url, dest)
        print("OK", ad_id, os.path.getsize(dest) // 1024, "KB")
    except Exception as e:
        print("FAIL", ad_id, type(e).__name__, str(e)[:180])


async def main():
    want = set(sys.argv[1:])
    hu = json.load(open(REFS))
    face_refs = [hu["locked"], hu["ref1-hero-amber"]]
    todo = {k: v for k, v in ADS.items() if not want or k in want}
    await asyncio.gather(*(gen(k, p, nf, face_refs) for k, (p, nf) in todo.items()))

asyncio.run(main())
