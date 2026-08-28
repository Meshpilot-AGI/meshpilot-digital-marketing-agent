import os, json, re, urllib.request, urllib.parse, asyncio
import asyncpg
from PIL import Image

REPO = os.path.expanduser("~/glitch-grow-ads-agent-private")
DSN = re.search(r'postgres(?:ql)?://[^\s"]+glitch_brain[^\s"]*', open(os.path.join(REPO, ".env")).read()).group(0)
HEYGEN = os.environ["HEYGEN_API_KEY"]; PIXABAY = os.environ["PIXABAY_API_KEY"]
BROLL = os.path.expanduser("~/india-persona/broll"); os.makedirs(BROLL, exist_ok=True)
BRAND = "ai-empire"; GROUP_SLUG = "ai-empire-broll"
GROUP_NAME = "AI Empire B-roll — social, work-from-home, marketing"

QUERIES = [
 ("woman laptop", 2, ["woman", "laptop", "work"]),
 ("social media", 2, ["social", "media", "phone"]),
 ("online business", 2, ["business", "online", "laptop"]),
 ("digital marketing", 2, ["marketing", "analytics", "ads"]),
 ("work from home", 2, ["home", "work", "laptop"]),
 ("smartphone apps", 1, ["phone", "apps", "social"]),
 ("indian woman computer", 2, ["indian", "woman", "laptop"]),
 ("instagram phone", 1, ["social", "instagram", "phone"]),
]

def pixabay(q, n):
    u = (f"https://pixabay.com/api/?key={PIXABAY}&q={urllib.parse.quote(q)}"
         f"&image_type=photo&per_page={max(n,5)}&safesearch=true&order=popular")
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    return [h["largeImageURL"] for h in d.get("hits", [])[:n]]

def dl(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
        f.write(r.read())

def hg_upload(path):
    data = open(path, "rb").read()
    req = urllib.request.Request("https://upload.heygen.com/v1/asset", data=data,
        headers={"X-Api-Key": HEYGEN, "Content-Type": "image/jpeg"}, method="POST")
    d = json.load(urllib.request.urlopen(req, timeout=120))["data"]
    return d["url"], d["id"]

async def main():
    items, seen, i = [], set(), 0
    for q, n, tags in QUERIES:
        try:
            for url in pixabay(q, n):
                if url in seen:
                    continue
                seen.add(url); i += 1
                dest = f"{BROLL}/broll-{i:02d}.jpg"; dl(url, dest)
                items.append((dest, tags)); print("dl", q, "->", os.path.basename(dest))
        except Exception as e:
            print("pixabay FAIL", q, type(e).__name__, str(e)[:80])

    conn = await asyncpg.connect(DSN)
    try:
        if not await conn.fetchval("SELECT brand_id FROM core.brands WHERE brand_id=$1", BRAND):
            cand = [r["brand_id"] for r in await conn.fetch("SELECT brand_id FROM core.brands ORDER BY brand_id")]
            print("BRAND ai-empire NOT in core.brands. candidates:", cand); return
        gid = await conn.fetchval("SELECT id FROM core.brand_asset_groups WHERE brand_id=$1 AND slug=$2", BRAND, GROUP_SLUG)
        if not gid:
            gid = await conn.fetchval(
                "INSERT INTO core.brand_asset_groups(brand_id,slug,name,description) VALUES($1,$2,$3,$4) RETURNING id",
                BRAND, GROUP_SLUG, GROUP_NAME,
                "Free Pixabay b-roll for the Video Agent: social platforms, girl working on laptop, digital marketing.")
            print("created group id", gid)
        added = 0
        for path, tags in items:
            try:
                url, aid = hg_upload(path)
            except Exception as e:
                print("upload FAIL", os.path.basename(path), str(e)[:80]); continue
            asset_id = await conn.fetchval("SELECT id FROM core.brand_assets WHERE brand_id=$1 AND url=$2", BRAND, url)
            if not asset_id:
                try: w, h = Image.open(path).size
                except Exception: w = h = None
                asset_id = await conn.fetchval(
                    "INSERT INTO core.brand_assets(brand_id,persona_id,kind,url,title,tags,mime_type,width,height,uploaded_by) "
                    "VALUES($1,NULL,'image',$2,$3,$4,'image/jpeg',$5,$6,'claude:aanya-broll') RETURNING id",
                    BRAND, url, os.path.basename(path), tags, w, h)
            await conn.execute("INSERT INTO core.brand_asset_group_members(group_id,asset_id) VALUES($1,$2) ON CONFLICT DO NOTHING", gid, asset_id)
            added += 1; print("registered", os.path.basename(path), "->", url)
        row = await conn.fetchrow("SELECT config FROM core.influencer_personas WHERE brand_id=$1 AND persona_id='aanya'", BRAND)
        cfg = row["config"]; cfg = json.loads(cfg) if isinstance(cfg, str) else dict(cfg)
        vi = cfg.setdefault("visual_identity", {})
        groups = set(vi.get("asset_groups") or []); groups.add(GROUP_SLUG); vi["asset_groups"] = sorted(groups)
        await conn.execute("UPDATE core.influencer_personas SET config=$1,updated_at=now() WHERE brand_id=$2 AND persona_id='aanya'", json.dumps(cfg), BRAND)
        n = await conn.fetchval("SELECT count(*) FROM core.brand_asset_group_members WHERE group_id=$1", gid)
        print(f"DONE group={GROUP_SLUG} id={gid} members={n} added_now={added} | Aanya asset_groups={vi['asset_groups']}")
    finally:
        await conn.close()

asyncio.run(main())
