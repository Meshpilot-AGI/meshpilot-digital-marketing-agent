# Engineering Supervisor — evidence log

> Append-only. Newest first. One entry per closed lane. See docs/LANE-LIFECYCLE.md §5.

### BUFFER-1 — Buffer per-brand, all-platform publishing — CLOSED 2026-08-28
**Owner:** Claude

**Read:** the existing buffer.py (already on the Buffer GraphQL API, but TikTok-only, video-only, global token); the Buffer REST→GraphQL migration guide.

**Changed:** token via `brand_env("BUFFER_API_KEY")` (no global); removed the tiktok-only block; added `list_channels`, `_channel_id_for_service` (dynamic account→org→channels, x/twitter aliased), and `create_post(service, text, media_url, mode)`; `/internal/buffer/{channels,test-post}` endpoints. Fixed `test_buffer.py` after the migration (a red CI had reached production — I compiled but hadn't run the suite). Applied 9 code-review security fixes across the session's code (fail-closed auth, XSS escape, token-at-rest hygiene, Sentry scrub, FB token→header, media-type-by-path, brand validation, dry-run guard).

**Verified (observed):** full suite green (286 passed). Live: `/internal/buffer/channels` returned GE's org + 3 channels (TikTok glitchexec, X GlitchExecutor, LinkedIn glitch-executor); `/internal/buffer/test-post` to X → real queued post `6a9253afe959557ce5549f08` (status scheduled).

**Notes / remains:** the blank `GE_BUFFER_API_KEY` was a FastAPI Cloud CLI quirk — `env set` won't UPDATE an existing var (only create); fixed via delete+recreate (documented in vendors/fastapi-cloud.md). Deferred from review: cross-brand auth isolation (#2), buffer first-org/channel selection, fire-and-forget scout tasks. Legacy video `publish()` still uses config-based channel ids.

---

### YT-1 — YouTube OAuth2 (per-brand refresh token) — CLOSED 2026-08-28
**Owner:** Claude

**Read:** the TikTok OAuth flow (oauth/tiktok.py + server.py handlers) + oauth/storage.py as the template; confirmed a service account cannot reach a YouTube channel (channels mine=True → 0).

**Changed:**
- GCP (driven via Chrome): created a Web OAuth client "meshpilot - GE YouTube" in the GE project (`cs-poc-…`), redirect `https://api.meshpilot.app/oauth/youtube/callback`, YouTube Data API v3 already enabled, consent screen In production/External. Downloaded JSON → `GE_YOUTUBE_CLIENT_ID` (cloud+local) + `GE_YOUTUBE_CLIENT_SECRET` (secret).
- `oauth/youtube.py` — authorize URL / code exchange / refresh, per-brand client via brand_env; tokens stored encrypted in PlatformAuth. `access_type=offline` + `prompt=consent`; refresh keeps the existing refresh_token.
- `server.py` — `/oauth/youtube/start`, `/oauth/youtube/callback`, and auth-gated `/internal/youtube/whoami`.
- `config` — youtube_redirect_uri + broad scopes (upload + youtube + force-ssl) for full channel management.
- Set global `AUTH_ENCRYPTION_KEY` (Fernet, secret) — required by crypto for token encryption + state signing (first 500 was this being unset). Keep stable.

**Verified (observed):** operator completed the consent → callback stored the refresh token (encrypted). `/internal/youtube/whoami?brand=glitch_executor` → **channel "Glitch Executor" (`UCky5yKjfKsEPb2K0ePZA-yw`)** — the OAuth token reaches the channel where the SA returned 0.

**Notes / remains:** wiring `platforms/youtube.py` upload to use `oauth.youtube.get_fresh_access_token` (per-brand) instead of the token file is a follow-on; the OAuth + storage foundation is done. Consent screen unverified → 100-user cap + "unverified app" warning (fine at this scale).

---

### GE-1 — per-brand env resolver + Meta Facebook publisher — CLOSED 2026-08-28
**Owner:** Claude

**Read:** docs/VISION.md, the Mesh Pilot bible (meshpilot_dashboard social_dispatch + social_agent influencer.meta_publish) for the FB Page publish + system-user→page-token flow; our config.py brand registry + brand.config.schema.

**Changed:**
- `config.brand_env(name, brand_id)` + `brand_env_prefix()` — the project-agnostic per-brand resolver. Reads `<ENV_PREFIX>_<KEY>` from the brand's `env_prefix`; no global fallback. `env_prefix` added to the default config + brand schema.
- `platforms/facebook.py` — Meta FB Page publisher: text→`/{page}/feed`, image→`/photos`, video→`/videos`; exchanges the per-brand system-user token for a page token; creds via `brand_env` (`GE_META_PAGE_ID`, `GE_SYSTEM_USER_TOKEN`). Payload/endpoint choice factored into pure `build_post()`.
- `meta_graph_api_version` setting; secured `POST /internal/facebook/test-post` (x-jobs-token); jobs/internal auth re-scoped to `GE_JOBS_AUTH_TOKEN` via `brand_env` (no global key).
- `docs/BRANDS.md` brand registry (GE = Glitch Executor); registered in DOC-SYSTEM.

**Verified (observed):**
- Unit tests: `test_brand_env.py` (4) + `test_facebook.py` (7) green.
- **Real Facebook post published from the cloud app** → post_id `1120765137796667_122116654083395430`, permalink live. Proves the full chain: brand_env resolve → system-user→page-token → `/feed` post.
- Auth gate enforced: `/internal/facebook/test-post` returns 401 without / with a wrong `GE_JOBS_AUTH_TOKEN` (verified against api.meshpilot.app after redeploy). `/healthz` 200.

**Notes / remains:** cloud env brand creds all `GE_`-prefixed; infra stays global. `GE_GOOGLE_DRIVE_SA_JSON` still a file path (needs inline-JSON for cloud). IG publisher + wiring the publisher into the scheduler/source are later lanes. DB-OPT (schema fits current workflow, not old SaaS) opened.

---

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

