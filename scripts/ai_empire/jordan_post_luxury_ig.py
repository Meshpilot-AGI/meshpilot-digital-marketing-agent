import json
import pathlib
import re
import sys
import time

import requests

G = "https://graph.facebook.com/v26.0"
PAGE = "1133702696499891"
IG = "17841478592958190"
HOST = "https://1c76c506.ai-empire-blueprint.pages.dev/jordan"

env = pathlib.Path("/home/ubuntu/glitch-grow-ads-agent-private/.env").read_text()
USER_TOKEN = re.search(r"^META_ACCESS_TOKEN=(\S+)", env, re.M).group(1)
PT = requests.get(f"{G}/{PAGE}", params={"fields": "access_token", "access_token": USER_TOKEN}, timeout=30).json()["access_token"]

POSTS = [
    ("jordan-luxury-lakehouse-deck.jpg",
     "Golden hour on the lake. The systems run, I watch the water. Took me years to learn it could work like this.\n\n#automation #freedom"),
    ("jordan-luxury-lounge-property.jpg",
     "Not about the house. It is about who is doing the work while I sit here. Spoiler: agents.\n\n#ai #automation"),
    ("jordan-luxury-ranch-estate.jpg",
     "Space to think. The ops run themselves these days - that was the trade I wanted all along.\n\n#aibusiness #systems"),
    ("jordan-luxury-home-deck.jpg",
     "Coffee, sunrise, zero fires to put out. Automation did more for my mornings than any alarm clock ever did.\n\n#automation #morningroutine"),
    ("jordan-luxury-home-patio.jpg",
     "Evenings look different when the business does not need you every hour. Building things that run without me was the unlock.\n\n#ai #buildinpublic"),
]

ok = 0
for fname, caption in POSTS:
    url = f"{HOST}/{fname}"
    if requests.head(url, timeout=20).status_code != 200:
        print(f"URL NOT LIVE: {url}"); continue
    r = requests.post(f"{G}/{IG}/media", data={"image_url": url, "caption": caption, "access_token": PT}, timeout=60).json()
    cid = r.get("id")
    if not cid:
        print(f"CONTAINER FAIL {fname}: {json.dumps(r)[:300]}"); continue
    time.sleep(3)
    r = requests.post(f"{G}/{IG}/media_publish", data={"creation_id": cid, "access_token": PT}, timeout=60).json()
    mid = r.get("id")
    if not mid:
        print(f"PUBLISH FAIL {fname}: {json.dumps(r)[:300]}"); continue
    perma = requests.get(f"{G}/{mid}", params={"fields": "permalink", "access_token": PT}, timeout=30).json().get("permalink")
    print(f"POSTED {fname} | ig={mid} | {perma}")
    ok += 1
    time.sleep(5)

r = requests.get(f"{G}/{IG}", params={"fields": "media_count", "access_token": PT}, timeout=30).json()
print(f"\nDONE {ok}/5 | IG media_count now: {r.get('media_count')}")
