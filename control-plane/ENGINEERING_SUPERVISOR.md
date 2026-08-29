# Engineering Supervisor — evidence log

> Append-only. Newest first. One entry per closed lane. See docs/LANE-LIFECYCLE.md §5.

### DEPLOY-1 — resolve upload-post dep + first FastAPI Cloud deploy — CLOSED 2026-08-28
**Owner:** Claude

**Read:** ClauseLens backend (`~/dev/leaselens-backend`) as the working reference; FastAPI Cloud docs (github-integration, database-migrations, env); the app's config/db/alembic/server modules.

**Changed:**
- Removed the private-fork `upload-post` dep (+ hatch `allow-direct-references`); its imports were already lazy. `uv lock` → 139 packages, no private access.
- Added `fastapi[standard]` (was bare `fastapi`) — FastAPI Cloud launches via `fastapi run`, which needs the extra; and `greenlet` (SQLAlchemy async needs it, not auto-installed on macOS arm64). Both were runtime-crash causes.
- DB config: read Supabase `DATABASE_URL` as fallback; normalize to asyncpg; `ssl="require"` (pooler self-signed cert); `statement_cache_size=0` for the pgbouncer pooler. Aligned Alembic (`env.py`) to the same resolver and bypassed configparser (%-in-password). 6 unit tests.
- CI: `.github/workflows/ci.yml` (uv sync + pytest + import smoke on PRs to main).
- Fixed `bin/vibe-lane` for macOS (BSD sed, bash 3.2).
- Cloud env: set `SIGNAL_DB_URL` (secret) to the proven us-east-2 session-pooler DSN.

**Verified (observed, not assumed):**
- Ran all 9 Alembic migrations against the Supabase project `qkztphfjwgluwwlgeyys` (region us-east-2, session pooler 5432) → `alembic current` = 0009; 14 tables present.
- First deploy built but crash-looped (bare `fastapi`); logs surfaced the cause; after the fix the redeploy is healthy.
- `GET /healthz` → 200 on both `https://meshpilot-social-media-agent.fastapicloud.dev` and the custom domain `https://api.meshpilot.app`, returning live DB-backed queue stats (proves the prod DB connection).

**Notes / remains:** the app runs `dispatch_mode=live` but the queue is empty, so nothing posts yet. To auto-deploy on merge, the FastAPI Cloud GitHub App still needs connecting in the dashboard (operator action). Direct `db.<ref>.supabase.co` is IPv6-only/unreachable locally — the session pooler is the IPv4 path.

---

### SETUP-1 — Bootstrap: standalone extraction + FastAPI Cloud wiring + GE brand creds — CLOSED 2026-08-28
**Owner:** Claude

**Read:** the Mesh Pilot monorepo `src/social_agent` (package `glitch_signal`); FastAPI Cloud getting-started + env docs; vibe-coding-kit THE-METHOD / LANE-LIFECYCLE / DOC-SYSTEM.

**Changed:**
- Extracted `src/social_agent` → this standalone repo (`glitch_signal` package kept to avoid rewriting imports). Proper folders preserved (`src/glitch_signal/…`, `alembic/`, `brand/`, `ops/`, `scripts/`, `tests/`).
- Decoupled the two monorepo imports: `brain.py` soft-imports `meshpilot_platform` (mirror self-disables when absent); `influencer/generate.py` lazy-imports `meshpilot_creative`.
- Added `main.py` (FastAPI Cloud entry → `glitch_signal.server:app`), `.fastapicloudignore`; renamed project to `meshpilot-social-media-agent`; old README preserved as `ARCHITECTURE.md`.
- FastAPI Cloud: logged in as the `helpn8nworld` account ("Mesh Pilot" team), linked this dir to app `meshpilot-social-media-agent` (`0d017e5b-1834-4952-8a77-b68f83ff2bfc`, us-east-1). Minted an app-scoped deploy token → local `.env` (gitignored).
- GE brand credentials (`GE_META_APP_ID`, `GE_META_APP_SECRET`, `GE_SYSTEM_USER_TOKEN`) pulled from `glitch-trade-app/.env.local` into both the local `.env` and the FastAPI Cloud app env (all `--secret`, `GE_` prefix to match the pre-existing `GE_BUFFER_API_KEY`).

**Verified:** whole package `compileall` clean; runtime-checked the brain guard disables the mirror when `meshpilot_platform` is absent; the deploy token authenticates as `help.n8nworld@gmail.com` and reaches app `0d017e5b…`; cloud `env list` shows all four `GE_` secrets. Commit is SSH-signed; no secrets committed (secret audit passed).

**Remains (opened as lanes):** GE-1 (per-brand `GE_` resolver + Facebook publisher — creds are staged but nothing reads them yet), BUFFER-1 (Buffer is TikTok-only today), DEPLOY-1 (`upload-post` private-fork dep blocks `uv sync`/deploy; external Postgres still needed).

---

