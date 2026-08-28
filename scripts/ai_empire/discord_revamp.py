#!/usr/bin/env python3
"""Revamp the dormant Mesh Pilot Discord into the AI Empire community.
REST-only (no gateway). Prints each op; 403s reported, not fatal."""
import json
import urllib.request

T = "MTQ3MDM1NDg2NzE2Mjk3MjE2MA.GMQxO0.9rjnpio2wvNkZ1W8grY-YCmuYyQS83-98A8SHk"
G = "1500994650763427851"
API = "https://discord.com/api/v10"


def call(method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bot {T}")
    req.add_header("User-Agent", "DiscordBot (https://buildaiempire.com, 1.0)")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Audit-Log-Reason", "AI Empire community revamp")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "_msg": e.read().decode()[:140]}


def report(label, res):
    print(("OK   " if "_err" not in res else f"FAIL({res['_err']}) ") + label +
          ("" if "_err" not in res else f" — {res['_msg']}"))


# ── guild name ───────────────────────────────────────────────────────
report("guild → AI Empire Builders",
       call("PATCH", f"/guilds/{G}", {"name": "AI Empire Builders"}))

# ── categories ───────────────────────────────────────────────────────
CATS = {
    "1501184428267933806": "📋 START",
    "1501184431610789928": "🌱 FREE ZONE",
    "1501184437516238961": "🔒 BLUEPRINT OWNERS",
    "1501184441639370752": "⭐ INNER CIRCLE",
}
for cid, name in CATS.items():
    report(f"category {name}", call("PATCH", f"/channels/{cid}", {"name": name}))

# ── channels: rename + topic ─────────────────────────────────────────
CH = [
    ("1501182789318606872", "rules", "Read first. Be useful, be honest, no spam, no fake earnings claims. This community practices what the Blueprint preaches."),
    ("1501184429261848779", "start-here", "New here? 1) Read #rules 2) Introduce yourself 3) Grab the free 7-day starter at buildaiempire.com 4) Building something? Post it in #wins."),
    ("1501184430318817413", "announcements", "Official updates from Jordan and the team — product updates, new modules, community news."),
    ("1501184433070542888", "seven-day-starter", "Questions and progress on the free 7-day starter plan. Day 1: pick one boring task. Start there."),
    ("1501184434639077528", "wins", "Ship it, show it. Agents built, hours saved, first orders — receipts welcome, hype optional."),
    ("1501184435914018926", "questions", "Stuck on anything automation — agents, prompts, pipelines, tools. Someone here has hit your wall already."),
    ("1501184439064068156", "blueprint-help", "Owners only: module-by-module help with the Blueprint. Reference the module number (01-07) when asking."),
    ("1501184440271896757", "owner-updates", "Owners only: new templates, module updates, early drops."),
    ("1501184442495139991", "inner-circle", "Reserved for what comes after the Blueprint. Quiet for now — deliberately."),
    ("1501864173393412118", "member-log", "Bot log: joins, role grants, purchase verifications."),
    ("1501864176077901834", "lead-log", "Bot log: lead + funnel events."),
]
for cid, name, topic in CH:
    report(f"#{name}", call("PATCH", f"/channels/{cid}", {"name": name, "topic": topic}))

# ── roles ────────────────────────────────────────────────────────────
roles = call("GET", f"/guilds/{G}/roles")
ROLE_MAP = {
    "Free Kit User": "Starter",
    "Agent Buyer": "Empire Builder",
    "Founder Stack Buyer": "Inner Circle",
    "Operator": "Operator",
}
if isinstance(roles, list):
    for r in roles:
        new = ROLE_MAP.get(r["name"])
        if new and new != r["name"]:
            report(f"role {r['name']} → {new}",
                   call("PATCH", f"/guilds/{G}/roles/{r['id']}", {"name": new}))

# ── welcome screen (community feature) ───────────────────────────────
report("welcome screen", call("PATCH", f"/guilds/{G}/welcome-screen", {
    "enabled": True,
    "description": "Build a business that runs itself. AI agents, automation, and the people actually doing it.",
    "welcome_channels": [
        {"channel_id": "1501184429261848779", "description": "Start here", "emoji_name": "👋"},
        {"channel_id": "1501184434639077528", "description": "See what people are building", "emoji_name": "🏆"},
        {"channel_id": "1501184435914018926", "description": "Ask anything", "emoji_name": "❓"},
    ],
}))

# ── permanent invite from #start-here ────────────────────────────────
inv = call("POST", "/channels/1501184429261848779/invites",
           {"max_age": 0, "max_uses": 0, "unique": True})
if "code" in inv:
    print(f"INVITE https://discord.gg/{inv['code']}")
else:
    report("invite", inv)

print("REVAMP DONE")
