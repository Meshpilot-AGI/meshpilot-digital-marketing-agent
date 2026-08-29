# Engineering Supervisor — evidence log

> Append-only. Newest first. One entry per closed lane. See docs/LANE-LIFECYCLE.md §5.

### CF-HARDEN — Cloudflare edge + origin hardening (mirrors leaselens) — CLOSED 2026-08-29
**Owner:** Claude

**Read:** leaselens-backend `app/{originauth,security,ratelimit,bodylimit}.py` + config (SEC #30 / ADR-010 — origin shared-secret gate); the CF zone/DNS/SSL state via the `~/.cloudflare` token.

**Changed:**
- **Part A (app middleware)** — new `src/glitch_signal/middleware/`: `SecurityHeaders` (HSTS/nosniff/X-Frame DENY/Referrer), `BodySizeLimit` (raw-ASGI, 2 MiB), `RateLimit` (sliding-window per-IP + global backstop, CF-aware `CF-Connecting-IP`), `OriginAuth` (fail-open; gates `/internal`+`/jobs`, exempts `/healthz`/`/oauth`/`/media/fetch`). Wired in `server.py` inner→outer + `TrustedHost` + optional CORS. Config knobs in `config.py`. 10 tests; suite 253 pass.
- **Part B (Cloudflare, live)** — flipped `api.meshpilot.app` to **proxied** (careful flip with auto-revert-if-broken; FastAPI Cloud works behind CF — `cf-ray` present, 200). Added a CF Transform Rule (`http_request_late_transform`) injecting `x-origin-auth: <secret>` on the API host (`operation: set`). Set `ORIGIN_SHARED_SECRET` (matching) as a cloud secret + redeployed → enforcement on. SSL mode already `full`.
- New `docs/vendors/cloudflare.md` runbook (zone/DNS, origin lockdown, ops, rollback).

**Verified (observed):** Part A live — security headers present, `/internal` works (jobs-auth), fail-open before enforcement. Part B live — **through CF** `/healthz`+`/internal` → 200; **direct to the FastAPI Cloud origin** (`…fastapicloud.dev`, no CF) → `/internal` **403** (origin locked), `/healthz` 200 (probes unaffected). Nothing broke (proxy verified before enforcing; health always open; origin-auth fail-open).

**Notes / remains:** CF config (proxy state, Transform Rule, SSL) lives in Cloudflare, not git — `docs/vendors/cloudflare.md` is the source of truth + rollback. Free plan → WAF managed rules limited; origin-auth + app rate-limit + body cap are the substantive controls (upgrade zone for full WAF). `ORIGIN_SHARED_SECRET` + the Transform Rule value must stay in lockstep.

---

### AGENT-MEM — per-brand agent memory (AGENT-BRAIN increment 1) — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the brainstorming skill; researched the real repos NousResearch/hermes-agent (memory-first + SKILL.md skills + curator + context compression) and openclaw/openclaw (trusted-gateway/policy) — both local personal-assistant CLIs, so we adopt patterns on our stack. Design spec: `docs/plans/2026-08-29-agent-brain.md` (operator-approved). Current agent is a fixed LangGraph video pipeline; the brain is new.

**Changed:** new `src/glitch_signal/agent/memory/` — `embeddings.py` (NVIDIA NIM `nvidia/nemotron-3-embed-1b`, 2048-dim, `input_type` passage/query, injectable client), `store.py` (`remember` = upsert fact-by-key / append episode; `recall` = fused `0.7*cosine + 0.3*ts_rank`, bumps last_used_at; degrades to lexical if embedding fails), `spec.py` (Memory). New idempotent migration `agent_memory` (halfvec(2048)+HNSW + FTS GIN + brand/key indexes, `create extension vector`). `server.py`: `/internal/agent/{remember,recall}` (x-jobs-token). CI `db` job image → `pgvector/pgvector:pg17` (vanilla postgres lacks pgvector). `NVIDIA_API_KEY` set as a global-infra cloud secret.

**Verified (observed):** 11 unit tests (fake embedder + fake engine + fake httpx, no network/DB); full suite **243 passed, 1 skipped**. Supabase applied the migration (vector 0.8.2 installed, `agent_memory` live, version recorded); CI `db` job built halfvec+HNSW on pgvector:pg17. **Live on api.meshpilot.app**: stored 2 GE facts (audience, voice) → recall paraphrases rank the correct fact #1 with clear semantic separation ("who are our customers" → audience sem .155; "what tone" → voice sem .231 vs audience −.005). Fixed one asyncpg pgvector type-inference bug (bind :qvec as text + `string_to_array` for id/kind arrays).

**Notes / remains:** AGENT-BRAIN increments 2–4 (LOOP → POLICY → LEARN) are next, each its own spec/PR. `brain.py`'s external glitch-brain-mcp mirror is superseded (remove in a later increment). Fusion weights + k are constants, tune on real data. NVIDIA free tier (starter credits + rate limits) is fine for build; embedder is injectable to swap providers. Model/dims pinned — changing the model needs a re-embed.

---

### VENDOR-1 — remove Upload-Post + redundant integrations; re-point publishing — CLOSED 2026-08-29
**Owner:** Claude

**Read:** docs/plans/2026-08-28-phase1-source-to-publish.md; the full blast radius across publisher.py, config._PUBLISH_PRIORITY, scheduler/queue.py, sheet_posting/, server routes, and every importer of the removed modules.

**Changed:**
- **New Meta Instagram publisher** `platforms/instagram.py` (per-brand creds via brand_env; page-token via facebook._fetch_page_token; image → `/media` + `/media_publish`, reel → REELS container + poll; needs a PUBLIC media URL, which STORAGE-1 provides). New `/internal/instagram/test-post`.
- **Repointed the publish path to Buffer/Meta/YouTube:** `_PUBLISH_PRIORITY` = tiktok/x/linkedin→buffer_*, facebook/instagram→meta_*, youtube→youtube_shorts (dropped threads/pinterest/bluesky/reddit). `publisher.py._publish_to_platform` now routes youtube_shorts / buffer_* / meta_facebook / meta_instagram only (builds a signed media URL + caption for Meta, via buffer helpers); webhook-pending sentinel now from buffer (`is_webhook_pending`/`extract_post_id`).
- **Scheduler:** `_reconcile_awaiting_webhook` is Buffer-only (dropped the upload_post poll); removed `_pull_post_analytics` (Upload-Post analytics).
- **Sheet poster** (`sheet_posting/{poster,reader,reconciler}.py`, via subagent + verified): normalizes the legacy `upload_post_*` platform values, resolves via `resolve_publish_platform`, posts through Buffer/Meta; quote_card renders + posts via a signed public URL; carousel **degrades to a single image** (no PDF); reconciler is a no-op (Buffer create_post is synchronous). Sheet read/write-back/audit preserved (test_sheet_tracker green).
- **Deleted:** platforms/{upload_post,tiktok,twitter}.py, webhooks/analytics/onboarding upload_post.py, integrations/{linkedin,x}.py, oauth/tiktok.py, the /oauth/tiktok/* + /webhooks/upload_post routes, and tests test_upload_post*.py + test_tiktok.py + test_upload_post_onboarding.py.

**Verified (observed):** app boots (`import server` + `scheduler.queue` clean); grep confirms **no live imports** of any removed module in src; full suite **232 passed, 1 skipped** (5 new IG unit tests). Real posts already proven earlier: Facebook (GE-1), Buffer X (BUFFER-1).

**Notes / remains:** **live IG post not yet run** (needs a public image + posts to GE's real IG — `/internal/instagram/test-post` is ready). `influencer/posting.py` left as dead code (it imports the top-level `upload_post` **pip** package removed in DEPLOY-1 — already non-functional, no active caller; a PRUNE candidate). Unused settings (`upload_post_api_key`, etc.) left harmless. carousel-as-PDF dropped; threads/pinterest/bluesky/reddit dropped (no publisher).

---

### SUPA-MIGRATE — adopt Supabase-native migrations, retire Alembic (DB-OPT part 1) — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the supabase skill; the live schema via the Supabase MCP (project qkztphfjwgluwwlgeyys — reachable only after the operator re-authed the MCP to the Meshpilot account; the local CLI is on a different account). Operator decisions: **replace Alembic**, push via the **Supabase GitHub integration**.

**Changed:** new `supabase/config.toml` (project ref + PG major 17) + `supabase/migrations/20260829054500_init_schema.sql` — the schema generated from `glitch_signal.db.models` (13 tables, exact match to the 13 live tables), written **idempotent** (`CREATE TABLE/INDEX IF NOT EXISTS` + `ENABLE ROW LEVEL SECURITY`) so it is a safe no-op on the existing prod DB and builds fresh preview/shadow DBs. **Retired Alembic**: deleted `alembic/` (9 migrations + env.py), `alembic.ini`, `.github/workflows/db-migrate.yml`, and the `alembic>=1.14` dep (uv.lock relocked → 167 pkgs). Repointed the `ci.yml` **db** job (drift on `supabase/migrations/**` or `db/**`) to apply the SQL migrations to a throwaway Postgres via `psql -v ON_ERROR_STOP=1`, then re-apply for idempotency. Updated `docs/vendors/supabase.md` + `.fastapicloudignore` (supabase/ excluded from the runtime bundle).

**Verified (observed):** baseline validated against the LIVE DB via MCP execute_sql — the idempotent DDL ran no-op with no error (proves valid SQL + matches existing schema). App boots; full suite **301 passed, 1 skipped** after Alembic removal + relock. Migration history on the project was empty; the idempotent baseline needs no manual schema_migrations poking.

**Notes / remains:** on the first merge to production, the **Supabase GitHub integration** applies the baseline (no-op) + records it — **watch its first run** in the Supabase dashboard (and confirm the integration watches `production`, since `preview` was retired). The app's runtime DB connection (SIGNAL_DB_URL/asyncpg) is unchanged. The **schema-slim half of DB-OPT** (drop the now-unused ORM tables comment_reply/strategic_reply/mention_event/orm_response + the video/scout tables if generation-only) is still open — do it as new supabase/migrations/*.sql. The stale `alembic_version` table lingers in prod (harmless; drop anytime).

---

### PRUNE-1 — remove ORM / comment-engagement subsystem — CLOSED 2026-08-29
**Owner:** Claude

**Read:** docs/plans/2026-08-28-phase1-source-to-publish.md; the blast radius (only `scheduler/queue.py` imports `comments/`+`orm/`, all lazy inside ticks); the scheduler tick loop.

**Changed:** deleted `src/glitch_signal/comments/` (sweeper, strategic, x_sweeper) and `src/glitch_signal/orm/` (classifier, guardrails, monitor, responder). In `scheduler/queue.py`: removed the 3 engagement ticks from `_tick()` and deleted their functions (`_send_orm_auto_responses`, `_poll_orm_mentions`, `_sweep_comments_tick` + `_comment_sweep_last`), dropped the now-unused `OrmResponse` top-level import, fixed the module docstring. Removed the ORM tests (`test_smoke.py` TestGuardrails + TestClassifierDryRun; `test_multi_brand_config.py` TestBrandScopedGuardrails). `ARCHITECTURE.md` ORM section marked removed.

**Verified (observed):** `import glitch_signal.server` + `scheduler.queue` boot clean; grep confirms **no remaining `glitch_signal.(comments|orm)` refs** in src; full suite **301 passed, 1 skipped** (was 310; −9 ORM tests). 

**Notes / remains:** the `OrmResponse`/`MentionEvent` **DB models** and the brand-config `orm_guardrails` field are intentionally left (DB-OPT removes the tables; `integrations/x.py` — now engagement-orphaned — is removed in VENDOR-1). This unblocks VENDOR-1: the engagement code that imported `integrations/x`, `integrations/linkedin`, and `upload_post` is gone.

---

### STORAGE-1 — persist generated media to per-brand Supabase buckets — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the cloud env Supabase vars (SUPABASE_URL / SUPABASE_SECRET_KEY / PUBLISHABLE / JWKS); the Supabase Storage REST API; the media-generation runner + Asset shape.

**Changed:** new `media/generation/storage.py` — `bucket_for(brand)` (= `<env_prefix>-media`, e.g. `ge-media`; brand-config `media_bucket` override), `ensure_bucket()` (idempotent create, tolerates 409/exists), `persist(asset, brand)` (download the engine URL → upload to `<bucket>/<recipe>/<uuid>.<ext>` → return Asset rewritten to the durable Supabase **public** URL, muapi URL kept in `metadata.source_url`). Uses the Storage REST API with the **service key** over httpx (no supabase-py dep). `/internal/media/generate` now persists by default (opt out `store:false`), returns `{url, source_url, bucket}`; new `POST /internal/media/ensure-bucket`. Updated `docs/vendors/supabase.md` (Storage section).

**Verified (observed):** 6 storage unit tests (fake httpx client — bucket-derivation, ext logic, upload+URL-rewrite, 409-tolerated, env-required); full suite **310 passed, 1 skipped**. Live on api.meshpilot.app: `ensure-bucket` created **`ge-media`**; `generate` (logo-creator) persisted → `https://qkztphfjwgluwwlgeyys.supabase.co/storage/v1/object/public/ge-media/muapi-logo-creator/39562526…png` → **HTTP 200, image/png, 341KB** (durable + publicly fetchable). `source_url` retained the muapi CDN URL.

**Notes / remains:** buckets are **public** (media is for public posts; publishers must fetch it) — switch to private + signed URLs if a brand needs it. Persistence lives in the endpoint; when the scheduler/publisher path is wired it should call `persist` too. Rationale: muapi CDN URLs expire ~30d, so brand-owned storage is required for durability + per-brand data isolation.

---

### MEDIA-2 — LLM composer (via muapi) + 7 more recipes — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the 9 remaining `~/dev/agent/skills/muapi-*` SKILL.md; `influencer/llm.py` (the app's Gemini-first completion); muapi's live model catalog (`GET /api/v1/models` → 655 models, categories) + the text-to-text call/result shape.

**Changed:** `compose.py` now routes prompt-authoring through **muapi's text-to-text models** (default `gemini-3-5-flash`) via the same `MuapiEngine` — muapi is a unified gateway (73 Text-to-Text models: Gemini/Claude/GPT/DeepSeek), same submit→poll contract, generated text in `outputs[0]`, so the **one `MUAPI_API_KEY` powers media AND text** (no separate LLM/Gemini key). Wired `compose=llm_compose` into `/internal/media/generate`. Added op `video.generate` (text→video). Bundled 7 recipes (SKILL.md + recipe.json): ad-creative, cinema-director, logo-creator, nano-banana, seedance-2, social-media-video, ui-design. Every model slug hand-verified against the live catalog + category-checked (fixed the subagent's `kling-master`→`kling-v2.5-turbo-pro-t2v`; logo/ui-design→`flux-2-pro` since their skills say "Flux"). Parity test relaxed to a family-token match (skills often name a model family in prose, not a literal slug). Updated `docs/vendors/muapi.md`.

**Verified (observed):** full suite **305 passed, 1 skipped** (new: composer via fake engine, empty-raises, 4-phase social-media-video chain, cinema-director text→video no-images, family-parity over all 11). Live on api.meshpilot.app: `/internal/media/recipes` → **11 recipes**; **`/internal/media/generate` on an LLM-authored recipe produced a real image** — `nano-banana` → `https://cdn.muapi.ai/outputs/generated/05dc1f6e107247c0b9a0c215c6b31474.png` (engine `muapi:nano-banana-pro`, 62s), proving muapi-text prompt authoring → image generation end-to-end.

**Notes / remains:** DEFERRED `muapi-ai-clipping` + `muapi-youtube-shorts` — both take an INPUT video via the managed clipping endpoint, outside the 5 generation ops (image.generate/edit, video.generate/from_image, llm). A future lane (MEDIA-3) could add a `video.edit`/clipping op. Multi-output packs (ad-creative's 4 formats, social-media-video's 8 platforms) modeled as a single primary asset per the runner's one-Asset contract. Composer model overridable via `MEDIA_TEXT_MODEL`.

---

### MEDIA-1 — vendor-pluggable media generation (MUapi) via the recipe library — CLOSED 2026-08-29
**Owner:** Claude

**Read:** docs/plans/2026-08-29-media-generation.md; the bible `meshpilot_creative/` (spec.py, engines/muapi.py submit→poll contract, router.py, recipes.py) for the reuse map; the 13 installed `~/dev/agent/skills/muapi-*` SKILL.md recipes (format: Inputs table + numbered `muapi <cmd>` phases with model + `{{prompt}}` templates + trigger keywords); the muapi CLI surface.

**Changed:** new `src/glitch_signal/media/generation/` — `engines/base.py` (Engine Protocol + EngineError), `engines/muapi.py` (httpx submit→poll→wait; POSTs to `{base}/{model}` directly since recipes carry real endpoint slugs — no curated model map); `spec.py` (Brief/Asset); `loader.py` (Recipe/Phase/InputSpec from a structured `recipe.json`, SKILL.md kept as bundled provenance); `registry.py` (slug + trigger lookup); `runner.py` (deterministic: fill `{{placeholders}}` incl. params, execute phases, output→next input, injectable engine + optional LLM composer). Bundled 4 starter recipes (product-video-ad-maker, ugc-video-factory, instagram-post, youtube-thumbnail) as `SKILL.md` (verbatim) + `recipe.json`. `server.py`: `/internal/media/recipes` + `/internal/media/generate` (x-jobs-token). New `docs/vendors/muapi.md` runbook.

**Verified (observed):** 14 new unit tests (fake engine, no network) — parse/fill/chain/trigger/param-render/missing-input/composer-required; full suite **300 passed, 1 skipped**. Live on api.meshpilot.app: `/internal/media/recipes` returns the library from the cloud; **`/internal/media/generate` produced a REAL video** — `product-video-ad-maker` → `https://cdn.muapi.ai/outputs/generated/8382032977314c54b96e22eceabbe271.mp4` (engine `muapi:wan2.5-image-to-video-fast`, 108s), proving image-edit → chain → image-to-video end-to-end.

**Notes / remains:** blank cloud `MUAPI_API_KEY` (the FastAPI Cloud `env set` create-only quirk again — deleted + set fresh + redeployed to fix). Template recipes need no LLM; **LLM composer for prompt-authored recipes (instagram/youtube/ugc) + the other 9 recipes = MEDIA-2**; fal/HeyGen engines, cost metering, and scheduler/publisher wiring are follow-ons. Resolves DB-OPT scope: generation IS in scope → keep signal/scout/video_asset/video_job.

---

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


### COST-METER INC-1 — per-brand vendor spend metering — CLOSED 2026-08-29
**Owner:** Claude

**Read:** industry approaches to multi-tenant AI cost attribution (self-meter at your own layer, mandatory tenant contextvar, usage event per call, price book, reconcile vs vendor aggregate); existing DB-backed patterns (`agent/loop/runs.py`, `agent/mcp/oauth.py`) for the `_engine` injectable-engine idiom; the loop LLM transport (`agent/loop/llm.py`) and Higgsfield engine as the two capture points readable at our layer today.

**Changed:**
- `supabase/migrations/20260829110000_usage_events.sql` — `usage_events` (brand_id, vendor, operation, model, units jsonb, cost_usd, estimated, request_id, created_at), two indexes, RLS on. Applied to prod Supabase (qkztphfjwgluwwlgeyys).
- `src/glitch_signal/analytics/cost/` — `context.py` (brand `contextvar`: set/get/`brand_scope`), `pricing.py` (Anthropic USD/MTok incl. cache-read/write; Higgsfield credits→USD; env-overridable via `COST_ANTHROPIC_PRICES` / `COST_HIGGSFIELD_*`), `meter.py` (`record_usage` fail-soft insert + Logfire gen_ai span gated on `LOGFIRE_TOKEN`; `spend_summary` per-vendor rollup).
- Capture: `agent/loop/llm.py` `_post` (response `usage` → `anthropic_cost` → record); `media/generation/engines/higgsfield.py` `generate` (base_credits → `higgsfield_cost` → record).
- Brand contextvar set at the boundaries: `agent/loop/runner.run`, `media/generation/runner.generate`, `agent/learn/curator.curate`.
- `GET /internal/analytics/spend?brand=&days=` (jobs-auth) → `spend_summary`.
- `docs/COST-METERING.md`; `tests/test_cost_meter.py` (10).

**Verified:** full suite **352 pass, 1 skipped** locally. Prod: `usage_events` present with all 10 columns; `/internal/analytics/spend` 200 (empty rollup pre-traffic). End-to-end — POST `/internal/agent/run` (glitch_executor) → run `done` → `/spend?days=1` returns **1 anthropic event, $0.010676**; DB row confirms model `claude-haiku-4-5-20251001`, 9956 input / 144 output tok, request_id captured, and cost math (9956×$1/M + 144×$5/M = $0.010676) checks. Commit SSH-signed; no secrets committed.

**Remains:** INC-2 — MUapi + HeyGen capture + a balance-delta reconciliation job (poll each vendor's queryable balance, diff vs summed events, alert on >5% drift, flip `estimated=false`) — this is how the credit vendors with no per-tenant tagging get trued up. INC-3 — per-brand budget enforcement in the policy gate + ops/anomaly view.

---

### AGENT-CRON — self-cron (the agent schedules its own work) — CLOSED 2026-08-29
**Owner:** Claude

**Read:** OpenClaw's Automations subsystem (`docs/automation/cron-jobs.md`, `src/agents/tools/cron-tool*.ts`, `src/skills/loading/workspace-skill-loader.ts`) as prior art; our own runtime — the per-worker in-process scheduler loop (`scheduler/queue.py`) and the DB-backed run-store pattern (`agent/loop/runs.py`); the loop tool registry (`agent/loop/tools.py`), policy gate (`agent/loop/policy.py`), and `runner.run` signature. Spec: `docs/plans/2026-08-29-agent-cron.md`.

**Changed:**
- `supabase/migrations/20260829120000_scheduled_jobs.sql` — `scheduled_jobs` + `scheduled_runs` (RLS). Applied to prod Supabase (qkztphfjwgluwwlgeyys).
- `src/glitch_signal/agent/cron/` — `schedule.py` (at/every/cron next-run via croniter + zoneinfo, no-drift interval), `store.py` (SKIP-LOCKED claim → advance/spend → open run in one txn = exactly-once; CRUD; finish_run success-reset / error-increment / auto-disable / one-shot delete; self-scoped delete), `capabilities.py` (allowlist: curate/drive_scout; reconcile=hook for COST-METER INC-2), `service.py` (sweep gated by kill-switch + rate-limited; dispatch agentTurn→runner.run+agent_runs / capability with wait_for; run_now for force), `tool.py` (self-scoped `schedule` create/list/cancel/next_check + creator-cap + duration parse), `runctx.py` (per-run job id for next_check pacing).
- Wired `_agent_cron_tick` into `scheduler/queue.py` `_tick`; registered `schedule` in the loop TOOLS map; `/internal/cron/*` endpoints in `server.py` (create/list/get/patch/delete/run/runs); config flags `agent_cron_enabled` (default False), `agent_cron_max_jobs_per_brand`, `agent_cron_max_failures`. Added `croniter` dep.

**Verified:** full suite **366 pass, 1 skipped**. Live (force-run, kill-switch off): capability=curate → `scheduled_runs.done` result `{lessons:3, episodes:5}`; one-shot agentTurn → `scheduled_runs.done` result `{run_id, steps:1}`, DB join confirms the linked `agent_runs` row is `done` steps=1, and the one-shot job auto-deleted. Commit SSH-signed; no secrets committed. Ships **disabled** — autonomous firing needs `AGENT_CRON_ENABLED=true` per env.

**Remains:** `stream`/`on-exit` triggers + webhook delivery (this subsystem, INC-2); COST-METER INC-2 supplies the `reconcile` capability body (then schedule it daily); the agent **self-skills / skill-workshop** corpus is a separate lane (the other OpenClaw gap).

### SECURITY — disable public API docs in production — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the FastAPI app construction in `server.py`; probed the live endpoints.

**Changed:** `server.py` FastAPI() now sets `docs_url`/`redoc_url`/`openapi_url` to None unless `settings().enable_api_docs`; new config flag `enable_api_docs` (default False). `tests/test_docs_disabled.py` (2).

**Verified:** `/docs`, `/redoc`, `/openapi.json` were public 200; after deploy all three return **404** through CF while `/healthz` and `/internal/cron/jobs` stay 200. Flagged by the operator (uneasy that the full API surface was public). Enable locally with `ENABLE_API_DOCS=true`.

---

### COST-METER INC-2 — MUapi/HeyGen capture + balance-delta reconciliation — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the capture points — `media/generation/engines/muapi.py` (also the content-text path, since `agent/llm.py` `chat()` calls the SAME `MuapiEngine.generate`) and `heygen.py`; INC-1's `analytics/cost/` (meter, pricing, context); probed vendor balance endpoints live (HeyGen `/v2/user/remaining_quota`=63; MUapi/Higgsfield need cloud keys).

**Changed:**
- `analytics/cost/pricing.py` — `muapi_cost` (coarse configurable default + per-model override), `heygen_cost` (credits×usd), `muapi_credit_usd`/`heygen_credit_usd`.
- Capture: `MuapiEngine.generate` `_meter` (vendor=muapi; covers text+media) + `HeyGenEngine.generate` `_meter` (vendor=heygen, credits) → `record_usage` with `get_brand()`. Fail-soft.
- `analytics/cost/reconcile.py` — per-vendor balance fetchers (heygen v2 quota; muapi `/account/balance`; higgsfield `/v1/account`, best-effort), `run()` snapshots into `balance_snapshots`, diffs vs previous snapshot (= true window spend), sums `usage_events` for the window, computes drift, warns >5%. Robust: a fetch failure records `unavailable`, never raises.
- Filled the AGENT-CRON `reconcile` capability hook; `POST /internal/analytics/reconcile` (jobs-auth); `supabase/migrations/20260829130000_balance_snapshots.sql` (RLS, applied to prod).
- `docs/COST-METERING.md` INC-2 marked done.

**Verified:** full suite **376 pass, 1 skipped** (updated the INC-1 hook test). Live (`POST /internal/analytics/reconcile`): MUapi balance **6.43** + HeyGen **63.0** resolve in prod; first call `baseline`, second call `reconciled` with `window_from` + delta/event-sum/drift computed (0 spend between calls → drift null); Higgsfield `unavailable` (405 — endpoint TBD, graceful). Seeded a nightly `capability=reconcile` cron job (30 3 * * * America/New_York) alongside nightly-curate. Commit SSH-signed; no secrets committed.

**Remains:** Higgsfield balance endpoint (currently unavailable); migrate HeyGen balance to `/v3/users/me` before the v2 sunset 2026-10-31; capture HeyGen **MCP-tool** calls (only the engine is metered today); reconciliation keeps `estimated=true` (aggregate delta can't set per-event true cost) — that's by design.

---

### COST-METER INC-3 + SECURITY SWEEP (floating-astronaut audit) — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the 18 open bug-bounty issues (#91–#108); validated each against the real code via 6 parallel read-only agents (verdicts in scratchpad/sdd-inc3-issues/val-*.md). All REAL, with nuances (#98 rate-limit weakness not auth bypass; #101 premature-opt; #103 inert under service-role).

**Changed (INC-3, PR #110):** `analytics/cost/budget.py` (clamp_steps hard ceiling + per-brand daily budget check, fail-open), enforced in `runner.run` + `_t_generate_media`; `GET /internal/analytics/budget`; config `agent_max_steps_ceiling`/`agent_brand_daily_budget_usd`. Closes #94.

**Changed (security, PRs #111/#112/#113):**
- #91 OAuth vendor tokens Fernet-encrypted at rest (`agent/mcp/oauth.py` + `*_enc` migration, dual-read); #96 get_bearer split into two short txns around the HTTP refresh (no lock across the call), timeout 30→10s.
- #97 usage_events partial unique index `(vendor,request_id)` + ON CONFLICT DO NOTHING.
- #92 `media/net.assert_safe_media_url` (https + public-IP only) + follow_redirects=False on edit_image.
- #93 MCP policy default-deny (allowlist wired via `<PREFIX>_MCP_ALLOW`, read-only verb prefixes, publish escape).
- #95 cron single-job store + endpoints brand-scoped (WHERE brand_id, `?brand=` required); `_require_jobs_auth` validates the target brand's token.
- #98 client_ip trusts CF/XFF only when ORIGIN_SHARED_SECRET set + startup warning; #100 durable-memory content capped 4000 chars; #105 cron lists LIMIT 500.

**Verified:** full suite **400 pass, 1 skipped**. Migrations applied to prod Supabase. Live: `/internal/analytics/budget` returns real spend + ceiling 12; brand-scoped cron auth still 200 for GE; MUapi/HeyGen reconcile balances resolve. Commits SSH-signed; no secrets committed. Issues #91,#92,#93,#94,#95,#96,#97,#100 closed on GitHub; #98/#101/#105 commented (partial/deferred).

**Remaining (validated, with fix plans):** #99 waitlist persistence (needs destination decision — form is static Cloudflare Pages so it must POST to the API); #102 CI action-pinning + permissions (needs `floating-astronaut` workflow-scope push); #98 shared-store move for rate-limit/webhook-dedup; #101 HNSW ORDER BY (tech debt); #103 RLS policies; #104 nginx/systemd; #105 platform_auth TOCTOU + forget() (dead code); #106 dead-code cleanup; #107 pytest warnings; #108 dep ceilings.

---
