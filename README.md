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

Live: **https://api.meshpilot.app** (custom domain) and
`https://meshpilot-social-media-agent.fastapicloud.dev`. App id
`0d017e5b-1834-4952-8a77-b68f83ff2bfc`, team `helpn8nworld` ("Mesh Pilot"),
region us-east-1.

**Manual deploy** (from this dir; uses `FASTAPI_CLOUD_TOKEN` in `.env`):
```bash
uvx --from "fastapi[standard]" fastapi cloud deploy .
```

**Auto-deploy:** connect the FastAPI Cloud **GitHub App** in the dashboard
(app → Settings → Source Repository → Connect). Only pushes to the **default
branch (`main`)** deploy.

### Runtime gotchas (learned the hard way — keep them)
- **`fastapi[standard]`** is required, not bare `fastapi` — the cloud launches
  the app via the `fastapi run` CLI, which lives in that extra.
- **`greenlet`** must be an explicit dep (SQLAlchemy async needs it; not
  auto-installed on every arch).
- **Cloud env vars** (dashboard/CLI, not the local `.env`): `SIGNAL_DB_URL`
  (Supabase **session pooler**, us-east-2 — the direct `db.<ref>.supabase.co`
  host is IPv6-only), the `GE_*` brand secrets, `GE_BUFFER_API_KEY`, and the
  Supabase API keys.

### Database (Supabase)
`config.py` reads `SIGNAL_DB_URL` (explicit wins) else `DATABASE_URL`,
normalizes to the asyncpg driver, uses `ssl="require"` (the pooler cert is
self-signed), and sets `statement_cache_size=0` for the pgbouncer pooler.

Run migrations manually (FastAPI Cloud has no migration hook), with the DSN in
`.env` — **additive migrations before deploy, removals after**:
```bash
uv run alembic upgrade head
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
