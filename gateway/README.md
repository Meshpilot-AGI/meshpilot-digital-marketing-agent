# MeshPilot channel gateway

A tiny, always-on bridge that lets you **talk to the MeshPilot agent from chat channels**.
It is *not* an agent — it's dumb plumbing. A message comes in on a channel, the gateway
forwards it to the MeshPilot agent's HTTP API, waits for the run to finish, and posts the
reply back on the channel. MeshPilot (on FastAPI Cloud) is always the brain.

This is our own lean version of OpenClaw's channel layer — one small file per concern, no
plugin framework. **Discord only for now**; Telegram / WhatsApp are future adapters.

## How it works

```
#agent-chat message
   → POST  {MESHPILOT_URL}/internal/agent/run  {goal, brand}   (header: x-jobs-token)
   → poll  GET  /internal/agent/run/{run_id}  until status = done|error
   → reply with `final` on the channel
```

Discord free-form chat needs a persistent gateway (websocket) connection, which is why this
runs as one always-on container (Railway, one replica) rather than on the stateless agent host.

## Run

```bash
pip install -r requirements.txt
export DISCORD_BOT_TOKEN=...            # the bot token
export DISCORD_AGENT_CHANNEL_ID=...     # the #agent-chat channel id
export MESHPILOT_URL=https://api.meshpilot.app
export MESHPILOT_JOBS_TOKEN=...         # the agent's jobs-auth token (x-jobs-token)
export MESHPILOT_BRAND=glitch_executor
python -u bridge.py
```

Enable **Message Content Intent** for the bot in the Discord developer portal, or it can't read
messages. Access control is the channel itself — `#agent-chat` is private (team + bot only), so
anyone who can post there is authorized.

## Deploy (Railway)

Builds from the `Dockerfile` (Railway root dir = `gateway`). Set the env vars above in the service.
No inbound port (it's a websocket client), so it needs no public domain or healthcheck.

**Branch-triggered deploy.** Railway watches the **`gateway-production`** branch and deploys on
push to it — the gateway ships on-demand, not on every `production` push. To ship:

```bash
git switch gateway-production
git merge --ff-only production      # this is the ship step
git push
git switch production
```

`gateway-production` is fast-forwarded from `production`, **never developed on** (a commit authored
directly on it forks it off `production` and breaks the ff path — the ~/dev commit-guard blocks it).
Railway has **wait-for-CI** on: because the ff carries the identical commit SHA, it gates on the
`gateway` build check (`docker build` + `py_compile`) that already ran on the `production` push —
so a broken Dockerfile or `requirements.txt` never reaches a deploy. (`railway up` from this dir
still works for a manual one-off, but the branch push is the normal path.)
