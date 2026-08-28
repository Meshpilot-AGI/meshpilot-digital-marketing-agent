import asyncio, os, json, re, asyncpg
os.chdir(os.path.expanduser("~/glitch-grow-ads-agent-private"))
env = open(".env").read()
DSN = re.search(r'postgres(?:ql)?://[^\s"]+glitch_brain[^\s"]*', env).group(0)

HEYGEN = {
    "group_id": "cd8cf1515e06468ebd64d3f1ed7d5f04",   # Aanya photo-avatar group (7 looks)
    "voice_id": "f09ffc6cdc4e41f7993c40c50b6c73ea",   # Riya Rao (Hindi female; HI+EN)
    "voice_name": "Riya Rao (Hindi)",
    "video_path": "video_agent",                       # enforce Video Agent path
}

async def main():
    conn = await asyncpg.connect(DSN)
    try:
        row = await conn.fetchrow(
            "SELECT config FROM core.influencer_personas WHERE brand_id='ai-empire' AND persona_id='aanya'")
        cfg = row["config"]
        cfg = json.loads(cfg) if isinstance(cfg, str) else dict(cfg)
        cfg["heygen"] = HEYGEN
        await conn.execute(
            "UPDATE core.influencer_personas SET config=$1, updated_at=now() "
            "WHERE brand_id='ai-empire' AND persona_id='aanya'", json.dumps(cfg))
        print("updated aanya.heygen:", json.dumps(cfg["heygen"]))
    finally:
        await conn.close()

asyncio.run(main())
