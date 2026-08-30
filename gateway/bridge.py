"""MeshPilot channel gateway — Discord ↔ the MeshPilot agent.

Our own thin bridge (not OpenClaw): a discord.py gateway bot that relays messages
in the private #agent-chat to the MeshPilot agent's HTTP API and posts the reply
back. The agent is always the brain; this is dumb plumbing. Runs as one always-on
container (Railway). Discord only for now — Telegram/WhatsApp are future adapters.

Flow: message in #agent-chat → POST /internal/agent/run {goal,brand} (x-jobs-token)
      → poll GET /internal/agent/run/{id} until done/error → reply with `final`.

Env:
  DISCORD_BOT_TOKEN          the bot token
  DISCORD_AGENT_CHANNEL_ID   the #agent-chat channel id (where people talk to the agent)
  MESHPILOT_URL              agent base URL (default https://api.meshpilot.app)
  MESHPILOT_JOBS_TOKEN       the agent's per-brand jobs-auth token (x-jobs-token)
  MESHPILOT_BRAND            brand id (default glitch_executor)
  AGENT_MAX_STEPS            per-turn step cap (default 6)
  POLL_INTERVAL_S / POLL_TIMEOUT_S   run polling cadence + ceiling
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("meshpilot.gateway")

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHAT_CHANNEL_ID = int(os.environ["DISCORD_AGENT_CHANNEL_ID"])
AGENT_URL = os.environ.get("MESHPILOT_URL", "https://api.meshpilot.app").rstrip("/")
JOBS_TOKEN = os.environ["MESHPILOT_JOBS_TOKEN"]
BRAND = os.environ.get("MESHPILOT_BRAND", "glitch_executor")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "6"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL_S", "2"))
POLL_TIMEOUT = float(os.environ.get("POLL_TIMEOUT_S", "180"))

intents = discord.Intents.default()
intents.message_content = True  # requires "Message Content Intent" enabled in the dev portal
client = discord.Client(intents=intents)


async def run_agent(goal: str) -> str:
    """Start an agent run for `goal`, poll to completion, return the final text."""
    headers = {"x-jobs-token": JOBS_TOKEN, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as h:
        # brand goes on the QUERY STRING: _require_jobs_auth validates the token against ?brand=, and
        # the handler now derives its target brand from ?brand= (not the body). A non-default brand
        # would otherwise 401/400. Keep it in the body too (must match) for backward compatibility.
        r = await h.post(
            f"{AGENT_URL}/internal/agent/run",
            headers=headers,
            params={"brand": BRAND},
            json={"goal": goal, "brand": BRAND, "max_steps": MAX_STEPS},
        )
        r.raise_for_status()
        run_id = r.json()["run_id"]

        loop = asyncio.get_event_loop()
        deadline = loop.time() + POLL_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            g = await h.get(f"{AGENT_URL}/internal/agent/run/{run_id}",
                            headers=headers, params={"brand": BRAND})
            g.raise_for_status()
            rec = g.json()
            status = rec.get("status")
            if status == "done":
                return (rec.get("final") or "").strip() or "(the agent finished but returned no text)"
            if status == "error":
                return f"⚠️ agent error: {rec.get('error') or 'unknown'}"
        return "⏱️ the agent is taking longer than expected — it may still finish; try again."


@client.event
async def on_ready():
    log.info("bridge online as %s (guilds=%d, chat_channel=%s)",
             client.user, len(client.guilds), CHAT_CHANNEL_ID)


@client.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.channel.id != CHAT_CHANNEL_ID:
        return
    goal = (msg.content or "").strip()
    if not goal:
        return
    log.info("relay: user=%s len=%d", msg.author, len(goal))
    async with msg.channel.typing():
        try:
            reply = await run_agent(goal)
        except Exception as exc:  # noqa: BLE001 — surface the failure to the user, don't crash the bot
            log.exception("agent call failed")
            reply = f"⚠️ couldn't reach the agent: {str(exc)[:200]}"
    # Discord caps a message at 2000 chars — chunk long replies.
    for i in range(0, len(reply), 1900):
        await msg.reply(reply[i:i + 1900], mention_author=False)


if __name__ == "__main__":
    client.run(TOKEN)
