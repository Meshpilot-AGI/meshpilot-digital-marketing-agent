# Mesh Pilot — Social Media Agent

Standalone, headless backend that generates social content with an LLM and
publishes it to social platforms on a recurring schedule. Extracted from the
Mesh Pilot digital-marketing monorepo as a single deployable service, targeting
**FastAPI Cloud** (merge to `main` → auto-deploy).

No frontend. The service is an API + an in-process scheduler + a LangGraph
content pipeline.

## What it does

1. **Generate** — a LangGraph agent (`agent/`) drafts brand-voiced content via a
   LiteLLM router that falls back across GPT / Gemini / Claude tiers.
2. **Schedule** — a background tick loop (`scheduler/queue.py`, every ~30s)
   dispatches `ScheduledPost` rows whose `scheduled_for` has arrived.
3. **Publish** — platform clients (`platforms/`, `integrations/`) post to the
   configured networks (LinkedIn, X, TikTok, Instagram, YouTube, …), directly or
   via a multi-platform vendor.

## Layout

```
main.py                 # FastAPI Cloud entrypoint → re-exports glitch_signal.server:app
src/glitch_signal/
  server.py             # FastAPI app + startup (builds graph, starts scheduler)
  config.py             # pydantic-settings; all config via env
  agent/                # LangGraph pipeline: llm router, graph, nodes/
  platforms/            # social publisher clients
  integrations/         # linkedin, x, google drive/sheets
  scheduler/            # the recurring dispatch tick loop
  sheet_posting/        # sheet-driven recurring posting
  media/ video_models/  # image/video generation + assembly
  db/                   # SQLModel models + async session
  oauth/ crypto.py      # per-platform OAuth token storage + Fernet encryption
  comments/ orm/        # reputation management (reply drafting, guardrails)
  influencer/           # persona engine (needs meshpilot_creative — not bundled)
alembic/                # DB migrations
brand/                  # brand config templates (*.example; real values are env/secret)
```

## Runtime

- **Python** ≥ 3.11, managed with `uv`.
- **Database**: external PostgreSQL (FastAPI Cloud has no managed DB — use
  Supabase or Neon). Connection via `SIGNAL_DB_URL`.
- **Scheduler**: runs in-process on app startup. The same dispatch is also
  reachable via an endpoint, so if the host scales to zero an external cron can
  drive it. See `scheduler/queue.py`.

## Local development

```bash
uv sync
cp .env.example .env        # fill in provider keys + SIGNAL_DB_URL
uv run alembic upgrade head
uv run fastapi dev main.py
```

## Deploy (FastAPI Cloud)

```bash
uv run fastapi deploy        # manual, or
# link this repo in the FastAPI Cloud dashboard → merge to main auto-deploys
```

## Decoupled from the monorepo

Two optional couplings to the original monorepo are guarded so this repo runs
standalone:

- `brain.py` (telemetry mirror to `meshpilot_platform`) — soft-imported;
  `brain_available()` returns False and the mirror is skipped when the SDK is
  absent.
- `influencer/generate.py` (`meshpilot_creative`) — imported lazily; only the
  influencer persona engine needs it, and it raises a clear error if invoked
  without the package.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full original design notes.
