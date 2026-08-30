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
   → POST  {MESHPILOT_URL}/internal/agent/run?brand={BRAND}  {goal, brand}   (header: x-jobs-token)
   → poll  GET  /internal/agent/run/{run_id}?brand={BRAND}   until status = done|error
   → reply with `final` on the channel
```

The `brand` goes on the **query string** of both calls: `x-jobs-token` is validated against
`?brand=`, and the agent resolves each run's target brand from `?brand=` (not the body), so a
non-default `MESHPILOT_BRAND` would 401/400 without it. It stays in the run POST body too, where it
must match the query value.

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

**Auto-deploys from `production`.** Railway watches the **`production`** branch with **watch paths
= `gateway/**`**, so it rebuilds and redeploys the gateway automatically whenever a push to
`production` changed something under `gateway/` — and stays untouched on the many API-only pushes,
so the Discord websocket doesn't reconnect for changes that don't concern it. **No manual step:**
merging a `gateway/` change into `production` ships it.

Railway does a **zero-downtime** rollout — the old bridge keeps serving until the new container is
healthy — and has **wait-for-CI** on, gating on the `gateway` build check (`docker build` +
`py_compile`) that runs on the `production` push whenever `gateway/**` drifts, so a broken
`Dockerfile` or `requirements.txt` never reaches a deploy. (`railway up` from this dir still works
for a manual one-off.)

> Retired 2026-08-30: the gateway used to ship by fast-forwarding a separate `gateway-production`
> branch. That manual dance is gone — Railway now deploys `production` directly via watch paths.
