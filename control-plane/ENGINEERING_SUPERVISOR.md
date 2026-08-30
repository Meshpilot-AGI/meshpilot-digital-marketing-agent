# Engineering Supervisor — evidence log

> Append-only. Newest first. One entry per closed lane. See docs/LANE-LIFECYCLE.md §5.

### SEC-BFLA — brand-scoped authz on the rest of the internal surface — CLOSED 2026-08-30
**Owner:** Claude

**Context:** `_require_jobs_auth` (server.py) brand-scopes the x-jobs-token to the brand in the `?brand=` query param (#95). The PIPELINE endpoints already take brand from `?brand=`, but **eight other** `/internal|/jobs` POST handlers still read `brand` from the JSON **body** — so a caller holding the default brand's jobs token (or any brand's, with no `?brand=`) could start actions for a *different* configured brand by naming it in the body (BFLA / cross-brand escalation).

**Read:** `_require_jobs_auth` + the fixed PIPELINE endpoints (`internal_agent_pipeline{,_schedule}`) as the reference pattern; `config.brand_ids/brand_env`; `tests/test_pipeline_endpoints.py` for the TestClient-with-monkeypatched-store style.

**Changed:** `src/glitch_signal/server.py` — added a `_authorized_brand(request, body)` helper that derives brand from the SAME source the token was authorized against (`request.query_params.get("brand") or "glitch_executor"`, validated against `brand_ids()`), and **400s if the body carries a `brand` that differs** from the authorized query brand (else silently acts on it). Replaced the `brand = body.get("brand", "glitch_executor")` idiom in all **8** remaining handlers: `POST /internal/agent/{remember,recall,run,curate}`, `POST /internal/cron/jobs`, `POST /internal/buffer/test-post`, `POST /internal/media/{generate,ensure-bucket}`. The GET handlers already read brand from a query param (safe, untouched). Single-brand (glitch_executor default) behavior is unchanged: no query + no body brand → the default brand, as before.

**Verified:** new `tests/test_internal_brand_auth.py` (7 tests, DB stores monkeypatched — no real Supabase hit) proves for `remember`/`run`/`cron.create` that a body brand differing from the authorized query brand → **400 with the action never executed** (store fake never called), while the no-body-brand and matching-body-brand paths still run on the authorized brand. `uv run pytest -q` → **501 passed, 1 skipped**. Ruff: 20 pre-existing issues before and after — **0 new debt** (none on the added lines).

**Docs:** this entry; `control-plane/ACTIVE_LANE_BOARD.md` (lane CLOSED).

**Remains:** none. (The two `raise HTTPException(...)`-without-`from` B904 warnings in the media handlers are pre-existing and out of scope.)

---

### README-REFRESH + repo hardening — CLOSED 2026-08-30
**Owner:** Claude

**Changed:** `README.md` refreshed to reflect the chat control plane — intro now says you can *talk to* the agent across channels ("our own OpenClaw, on managed cloud"), a new **Talk to it (chat control plane)** section describes the Discord gateway (`gateway/`), plus a TOC entry and a live-state note. Repo hardening (via `gh api`, floating-astronaut): **branch protection** set — `production` requires a PR (0 approvals, enforce_admins off) and blocks force-push/deletion; `web-production` blocks force-push/deletion but allows the ff deploy pushes. **`#github` live feed**: created a Discord channel webhook in #github and registered a GitHub repo webhook (id 672167539, events push/pull_request/issues/release/star) pointing at it.

**Verified:** `gh api` returns `production: PR-required=true, force_push=false, deletions=false` and `web-production: PR-required=false, force_push=false, deletions=false`; repo hook active; README headings/anchors + both mermaid diagrams intact.

**Remains:** none for this lane.

---

### GATEWAY-1 — Discord ↔ MeshPilot bridge — CLOSED 2026-08-30
**Owner:** Claude

**Context:** operator's vision — MeshPilot is "our own OpenClaw" (talk to one agent across chat channels) but on managed cloud, not a VM, and simpler. Studied OpenClaw's real source (github.com/openclaw/openclaw, MIT, cloned) — its channels are a heavy plugin framework inside an always-on Node gateway; running it (even as a gateway via a CLI-backend shim) drags 643MB + its session/watchdog machinery. Decision: **build our own lean bridge**, adapting only the patterns. Discord-only for now (Telegram/WhatsApp are future adapters).

**Changed:** new `gateway/` in the agent repo — `bridge.py` (~90 lines, discord.py gateway bot, `message_content` intent) + Dockerfile + requirements + railway.json + README. Flow: message in `#agent-chat` → `POST {MESHPILOT_URL}/internal/agent/run {goal,brand}` (header `x-jobs-token`) → poll `GET /internal/agent/run/{id}` until `done`/`error` → reply with `final` (chunked at 2000 chars). Access control = the channel's own privacy (`#agent-chat` is Team+bot only). No inbound port (websocket client).

**Infra:** deployed to Railway service `meshpilot-digital-marketing-agent` (project "Mesh Pilot - Gateway", id 83c226d5…) via `railway up` — one always-on replica, managed container (fits "no VM"). Env on Railway: DISCORD_BOT_TOKEN, DISCORD_AGENT_CHANNEL_ID (#agent-chat 1543461321809338419), MESHPILOT_URL, MESHPILOT_JOBS_TOKEN, MESHPILOT_BRAND. **`GE_JOBS_AUTH_TOKEN` rotated** (Claude-generated `secrets.token_urlsafe(36)`), set on BOTH FastAPI Cloud env and the bridge; the agent was redeployed (env changes need a redeploy) — probe confirmed the new token live (200). Set the service **Root Directory = `gateway`** in the Railway dashboard (driven via Claude-in-Chrome) so a push deploys the bridge, not the whole agent — a prior GitHub auto-deploy of the full repo had FAILED at build (harmless: a failed build never replaces the active deploy).

**Verified:** Railway logs — `bridge online as meshpilot_agent#8654 (guilds=1, chat_channel=1543461321809338419)` (connected to Discord gateway with no PrivilegedIntentsRequired → Message Content Intent is on). End-to-end run test via the bridge's exact call path returned the agent's real answer ("I'm a Digital Marketing AGI … for Glitch Executor"). **Operator confirmed** talking to MeshPilot in `#agent-chat` works live.

**Remains:** delete the unused Railway deploy-webhook pointed at `api.meshpilot.app/railway/webhook` (404s). Future increments: agent → Discord notifications (post to `#agent-activity` / `#alerts`, incl. a `/railway/webhook` receiver for deploy events); Telegram + WhatsApp (Meta Cloud API) adapters; a superseded in-app Discord attempt is stashed on `lane/discord-control-plane`.

---

### EMAIL-1 — the agent's email capability (Resend), gated OFF — CLOSED 2026-08-30
**Owner:** Claude

**Read:** the operator's goal ("give our agent full mailing capacity") + the resend-python SDK; the existing patterns to mirror — `agent/loop/policy.py` (gate), `agent/loop/tools.py` (tool registry + how the runner calls `policy.allow` at runner.py:114), `server.py` `/webhooks/heygen` (signature-verify + `webhook_seen` dedup), `middleware/{ratelimit,originauth}`, `middleware/shared_state.SharedWindowLimiter`.

**Design (operator-approved):** email as an agent capability, **gated OFF** (send immediately was offered + declined), webhook on **api.meshpilot.app/resend/webhook** (the path the operator configured in Resend).

**Changed:**
- Dep: `resend==2.42.0` (`uv add`).
- `comms/email.py` (new) — `send_email(brand_id, to, subject, html?/text?, from?)`: per-brand From resolution (override → `<PREFIX>_RESEND_FROM` → brand config `email.from` → `RESEND_FROM`), content-policy `strip_footprints` on subject+body, `DISPATCH_MODE=dry_run` short-circuit, per-brand **daily cap** via `SharedWindowLimiter(cap, 86400)` over `rate_counters` (no new table), sync SDK wrapped in `asyncio.to_thread`. Empty/whitespace recipients filtered.
- Policy gate (`agent/loop/policy.py`): `EMAIL_TOOLS={"send_email"}`, `Policy.email_enabled` + `max_emails_per_run`, gate rule 3b (deny unless enabled + per-run cap), wired in `from_config`.
- Loop tool `send_email` (`agent/loop/tools.py`) — gated by the runner's existing `policy.allow` call.
- `POST /resend/webhook` (`server.py`) — **Svix** verify: HMAC-SHA256 over `{svix-id}.{svix-timestamp}.{body}`, key = base64-decoded `whsec_…`, match any `v1,<b64>` in `svix-signature`; 5-min replay window; fail-closed 503 with no secret; dedup on `svix-id`. Added `/resend/webhook` to the rate-limit exemption (origin-auth already ignores it — not /internal|/jobs).
- Config: `resend_api_key`, `resend_webhook_secret`, `resend_from`, `agent_email_enabled` (default False), `agent_max_emails_per_run` (5), `agent_email_brand_daily_cap` (50). `.env.example` documented. `SOUL.md` gains an **Email** channel + its gating rule.
- Env (FastAPI Cloud secrets, set this session): `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET` (rotated to the api.meshpilot.app webhook's value).

**Verified:** `tests/test_email.py` — 14 tests: gate (deny-when-off / allow-when-on / per-run cap / off-by-default), send (dry-run mock id, missing recipient/body/From raise, content-policy strips em-dash before the captured Resend call, daily-cap denial), webhook (valid Svix sig → 200, bad sig → 401, missing headers → 400, stale → 400, no-secret → 503). Full suite **445 passed, 1 skipped**. Ruff: 0 new debt (existing files unchanged at 12; new files clean). Import smoke + gate invariants confirmed live.

**Remains (EMAIL-2):** bounce/complaint → suppression list + agent-memory feedback (the webhook currently verifies + logs only); inbound-reply parsing (Resend inbound); real per-brand From in brand configs. **Sending is OFF** until the operator sets `AGENT_EMAIL_ENABLED=true`. Minor: `.env.example` still carries stale `UPLOAD_POST_*` entries (VENDOR-2 cleaned the code, missed this file) — flag for a doc-cleanup pass.

---

### SUPA-HARDEN — close the two Supabase security-advisor WARNs — CLOSED 2026-08-30
**Owner:** Claude

**Read:** live security advisor (`get_advisors` security) for project `qkztphfjwgluwwlgeyys`; `pg_extension` / `pg_roles` search_paths / `pg_event_trigger` / column-type deps via `execute_sql`; `supabase/migrations/`.

**Context (the actual finding):** the post-open-source review asked whether `supabase/` + `web/` being public is safe. It **is** — no secrets committed (all `env()` refs), `.next` git-ignored, and the live DB is **RLS deny-all on all 24 tables** (anon publishable key returns `200 []` on every table — correctly denied, not leaking). Publishing the schema exposes nothing exploitable. The advisor did flag two WARNs worth fixing as defence-in-depth.

**Changed:** new migration `supabase/migrations/20260830010000_supa_harden.sql` (idempotent):
- **`revoke execute on function public.rls_auto_enable() from public, anon, authenticated`** — closes advisor lints 0028/0029 (anon/authenticated could call this SECURITY DEFINER fn via `/rest/v1/rpc/rls_auto_enable`). It's wired to the `ensure_rls` EVENT TRIGGER, which fires on DDL independent of EXECUTE grants — so the auto-RLS behaviour is unaffected; only the public RPC surface is removed.
- **`alter extension vector set schema extensions`** (guarded; `create schema if not exists extensions` first) — closes lint 0014 (extension in the API-exposed `public` schema). Safe here: the `extensions` schema pre-exists (Supabase default), the app connects as `postgres` whose search_path is `"$user", public, extensions` (so unqualified `halfvec` / `<=>` still resolve), and only one column depends on the type (`agent_memory.embedding halfvec(2048)`; its HNSW index follows via pg dependency tracking).

**Outcome — BOTH WARNs cleared on prod; a migration-hygiene wrinkle found and resolved:**
- PR #140 (naive `revoke`) failed the from-scratch CI gate: `rls_auto_enable()` isn't in these migrations (out-of-band Supabase fn), so the throwaway DB lacks the function → `does not exist`. Guarded it.
- PR #141 (guarded revoke **+ extension move**) failed the CI **idempotency re-apply**: after `alter extension vector set schema extensions`, the earlier agent_memory HNSW migration re-applies with an UNQUALIFIED `halfvec_cosine_ops` that the CI's `psql` (search_path = public) can't resolve. Prod's `postgres` role HAS `extensions` in its path, so it's fine there.
- **Key discovery:** the Supabase↔GitHub integration applies migrations to prod **independently of the CI result**. Version `20260830010000` was applied to prod with the **revoke + move** content (recorded in `schema_migrations`, 3 statements) — so **BOTH WARNs were actually cleared on prod** (verified: `vector` in `extensions`, `rls_auto_enable` grantees = `postgres, service_role`, advisor clean of all WARN-level lints). But then PR #142 shrank the file to revoke-only for CI-green — creating a **drift**: committed file ≠ what prod applied ≠ from-scratch-reproducible.
- **Resolved (PR #143, SUPA-HARDEN-ENCODE):** restored the migration to the full guarded revoke+move (matching prod's applied content) AND set `PGOPTIONS: -c search_path=public,extensions` on the CI db job (mirrors prod's `postgres` search_path) so the from-scratch + idempotency passes resolve `halfvec_cosine_ops` after the move. Now: file == prod == from-scratch, CI green. The already-recorded prod version is not re-applied (idempotent guards make it a no-op if it ever were).

Verified on the live DB (post-integration-apply): `migration_applied=true`, `vector` in `extensions`, `rls_auto_enable` not executable by anon/authenticated/PUBLIC, security advisor shows **zero WARN-level lints** (only the by-design `rls_enabled_no_policy` INFO). No app code changed.

**Lesson (→ memory):** never reuse a migration VERSION number with different content across pushes — the integration may apply an intermediate version, then skip later same-version files, leaving file≠prod. Use a NEW version per change.

**Remains:**
- **⚠️ `ensure_rls`/`rls_auto_enable` not in migrations:** the auto-RLS trigger lives only on prod. A from-scratch rebuild would NOT reproduce RLS on the ~13 tables that rely on it (they'd be RLS-off). Worth a lane to codify the trigger into a migration so from-scratch == prod. (The one genuinely-important follow-up.)
- `rls_enabled_no_policy` INFO notices persist by design (deny-all; app is service-role only) — not a vuln.

---

### BOARD-TIDY — board hygiene + AGENT-BRAIN epic closed — CLOSED 2026-08-29
**Owner:** Claude

**Changed:** `control-plane/ACTIVE_LANE_BOARD.md` — the Active section had a **duplicate `## Active` heading** carrying the AGENT-BRAIN epic whose five sub-lanes (MEM/LOOP/POLICY/LEARN/CRON) were all already CLOSED. Moved AGENT-BRAIN to Recently closed as a single "epic complete" entry and removed the stray heading, so **Active now shows only genuinely-open work** — just `DB-OPT [PARKED]`.

**Verified:** exactly one `## Active` heading remains; Active lists only DB-OPT.

**Rule reinforced (operator, 2026-08-29):** the board is the **single source of truth** — update it **before AND after every coding task** (register/claim the lane before code; close it after). If it's stale on arrival, fix it first. Saved to agent memory.

---

### README-SEO — flagship README polish + org profile — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the existing README (350 lines, strong on substance but no OSS "chrome"); the org's public repo list (flagship + MCP servers + ai-* agents); the repo's GitHub metadata (description/topics/homepage all empty).

**Changed:**
- `README.md` — added a centered **hero** (🛰️ MeshPilot + one-line tagline), an **8-badge row** (License AGPL / Python 3.11+ / FastAPI / Claude / CI status / live-API uptime / PRs-welcome / GitHub stars), a **Contents TOC**, a keyword-rich SEO intro, renamed "Build & run" → "Quickstart", merged the duplicate Git-hosting + Contributing sections, added a slim **Ecosystem** pointer to the org (NOT the full portfolio table — that belongs at org level; operator flagged the duplication), and a star-CTA footer. Fixed the stale `Nuraveda-Labs` org reference (repo is `Meshpilot-AGI` now).
- **GitHub repo metadata** via `gh repo edit`: description, homepage `meshpilot.app`, and **18 SEO topics** (ai-agent, autonomous-agents, agentic-ai, digital-marketing, marketing-automation, social-media-automation, llm, claude, anthropic, fastapi, python, open-source, self-hosted, content-generation, mcp, supabase, seo, generative-ai). All three were empty — the single biggest discoverability gap, since GitHub search + Google index those fields.
- **New org profile**: created `Meshpilot-AGI/.github` (public) with `profile/README.md` — renders on the org landing page (github.com/Meshpilot-AGI): hero, flagship callout, full agent/MCP portfolio table (linkedin-ads-mcp, shopify-agentic-seo-app, ai-{seo,ads,social,ugc,sales,voice}-agent), and a "what we believe" section.

**Verified:** TOC anchors match headings; both mermaid diagrams intact; `gh repo view` confirms description + 18 topics live; `gh api` confirms `profile/README.md` (3211 bytes) is on the `.github` repo. Org commit SSH-signed, authored as Tejas.

**Remains:** a logo / social-preview `og:image` would further lift click-through — currently text + emoji only (optional).

---

### OSS-PREP — open-source licensing prep (AGPL-3.0) — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the open-core strategy (memory `meshpilot-open-core-strategy` — Supabase model: agent open + self-hostable, hosted multi-tenant SaaS is the paid product); the existing README/pyproject; the full commit history for secrets.

**Changed:** `LICENSE` — full **AGPL-3.0** text (network copyleft: a hosted or modified fork must publish its source, protecting the future managed-SaaS product). `README.md` — open-core framing up top (this agent is free + self-hostable; the managed multi-tenant platform is the paid product, "same model as Supabase") + License / Contributing / Acknowledgements sections (credits Hermes/NousResearch + OpenClaw, per operator — "we took a lot from openclaw and hermes"). `CONTRIBUTING.md` — doc-driven/lane workflow, AGPL inbound=outbound contribution terms, hard no-secrets rule, uv-based setup. `.gitleaks.toml` — extends the default ruleset; allowlists ONLY the fixed dummy test Fernet key (`l3mgT3…`, which protects nothing real — prod `AUTH_ENCRYPTION_KEY` is env-injected) + `.env.example`. `pyproject.toml` — classifier `License :: Other/Proprietary License` → `License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)`; Repository/Issues URLs → `Meshpilot-AGI` org (repo was transferred from xenon2512).

**Verified:** `gitleaks detect` full-history scan — **103 commits, 3.88 MB, no leaks found** → clean for public release. Suite **431 passed, 1 skipped**. pyproject sanity: `license = {file="LICENSE"}` + AGPLv3+ classifier + Meshpilot-AGI URLs. (Blocker from the WIP state — "suite green pending upload-post removal" — resolved by VENDOR-2, which this lane rebased onto.)

**Repo is PUBLIC:** the operator flipped it to public 2026-08-29, right after this prep — the full-history gitleaks scan (no leaks) means nothing sensitive was exposed. Optional later: a NOTICE/attribution file if any Hermes/OpenClaw-derived code needs per-file headers; a short "why AGPL, not MIT/Apache" note for contributors.

---

### VENDOR-2 — remove Upload-Post completely — CLOSED 2026-08-29
**Owner:** Claude

**Read:** VENDOR-1's board entry (its explicit "Remains: influencer/posting.py left as dead code, imports the removed upload_post pip pkg"); the live publish path — `config._PUBLISH_PRIORITY` + `resolve_publish_platform`, `agent/nodes/publisher._publish_to_platform`, `platforms/buffer.py` (its own `awaiting_webhook` + poll-reconcile, `_CANONICAL` map), `influencer/pipeline.posting_tick` + `posting.py`, `agent/nodes/text_writer.py`, `media/ffmpeg.canonical_platform`, `sheet_posting/{reader,poster}.py`, `brand/schema/brand.config.schema.json` + `configs.example/`. Confirmed no real GE brand config is in the repo (external) and no live `/webhooks/upload_post` route exists (only `/webhooks/heygen`).

**Changed:**
- Deleted `src/glitch_signal/influencer/posting.py` (Upload-Post-only publisher; imported the removed `upload_post` pip pkg — VENDOR-1's leftover dead code). `influencer/pipeline.posting_tick`: the non-Meta else-branch (was `posting.post_asset`) now raises a loud "no publisher" — the pipeline is Meta-Graph-only, matching its existing `_postable_personas` Meta gate; dropped the `posting` import + fixed the module docstring.
- `config.py`: removed dead settings `upload_post_api_key`, `upload_post_status_timeout_s`, `upload_post_webhook_secret`; renamed `upload_post_webhook_reconcile_after_s` → `webhook_reconcile_after_s` (its sole consumer is the Buffer async-reconcile sweep). Cleaned the LinkedIn/Buffer/analytics/routing comments.
- Platform-key convention `upload_post_` → `buffer_`/`meta_`: `text_writer.py` now produces `buffer_x`/`buffer_linkedin` — **fixes a latent break**, since `_publish_to_platform` only routes `buffer_*`/`meta_*`/`youtube_shorts` and would have raised "Unknown platform" on the old keys. `ffmpeg.canonical_platform` now strips `buffer_`/`meta_` (also fixes a silent transform-lookup miss where `buffer_tiktok` didn't canonicalize to `tiktok`). `sheet_posting/reader.py` + `poster.py` share a new vendor-neutral `strip_publisher_prefix` (strips buffer_/meta_/zernio_).
- `brand/schema/brand.config.schema.json` + `configs.example/drive_footage_brand.example.json`: `upload_post_{tiktok,instagram,youtube}` blocks renamed to `buffer_tiktok`/`meta_instagram`/`youtube_shorts` (platforms object is `additionalProperties:true`, so this is doc-only, no validation risk).
- All remaining Upload-Post prose (comments/docstrings across ~15 files) reworded vendor-neutral (buffer.py's TikTok synthetic-media-mute rationale preserved as "the prior TikTok publisher").
- `tests/test_dispatch_gate_inflight.py`: anchored test `now` to midday UTC. Pre-existing flake (unrelated to this removal, surfaced during it): seeds used `now - 1h`/`-2m`, which cross UTC midnight when the suite runs 00:00–01:00 UTC, so `_count_posts_today` (counts `last_attempt_at >= today-midnight`) intermittently returned 0 → the "2–4 failing, order/time dependent" behavior. Also updated the fixture platform key + docstring.

**Verified (observed):** repo-wide `grep -rniE "upload.?post|UploadPost"` clean in src/ tests/ brand/. Full suite **431 passed, 1 skipped** (previously intermittently 2–4 failing on the midnight flake, now deterministic). ruff clean on every changed file. Import smoke-test: all touched modules load, deleted `posting` import gone, `settings().webhook_reconcile_after_s` present + `upload_post_api_key` absent, `strip_publisher_prefix('buffer_linkedin')=='linkedin'` / `('meta_facebook')=='facebook'` / `canonical_platform('buffer_tiktok')=='tiktok'`. No prod risk: publishing is OFF pre-launch and GE's live config already uses `buffer_*`/`meta_*` (the publisher has mandated those since VENDOR-1) — this migration aligns code to shipped reality.

**Remains:** `zernio_` prefix untouched (separate legacy vendor, out of scope — still in schema + `canonical_platform` + `strip_publisher_prefix`); the standalone sheet-poster still posts operator-authored captions unsanitized (unchanged, by design). Nothing Upload-Post-related remains anywhere in the code.

---

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

### SECURITY SWEEP — second wave (#99, #102, #103, #104, #105, #106) — CLOSED 2026-08-29
**Owner:** Claude

**Changed:**
- #99 waitlist: `POST /waitlist` (public, rate-limited, strict email check) → new `waitlist` table (unique lower(email)); `web/components/waitlist-form.tsx` POSTs to the API with loading/error/success; `CORS_ALLOW_ORIGINS=https://meshpilot.app`. **Verified live**: 200 valid / 422 invalid / CORS preflight 200 / idempotent (1 row on double-post).
- #102 CI: pinned actions/checkout, actions/setup-node, astral-sh/setup-uv to commit SHAs + top-level `permissions: contents: read` (pushed via floating-astronaut, workflow scope).
- #103 RLS: closed as by-design (service-role-only access; RLS default-deny is the intended model).
- #104: nginx edge security headers added; systemd units already sandboxed (box-era files; app sets the same headers via SecurityHeadersMiddleware).
- #105: platform_auth unique index (brand_id, platform, coalesce(account_identifier,'')) closes the upsert TOCTOU; cron lists already bounded (#113). forget() brand-scope = dead code, closed.
- #106: removed dead code (discord/ with on-box secret paths, a broken influencer script, 3 unused web components carrying tabnabbing + HTML-injection landmines); kept db/__init__.py (package marker).

**Verified:** suite **402 pass, 1 skipped**; web build clean; migrations applied to prod; waitlist + budget + brand-scoped cron auth all confirmed live. 14/18 audit issues closed; 4 deferred with reasoning (#98 shared-store move, #101 premature-opt, #107 warnings, #108 dep ceilings).

---

### #107 — SQLModel session.exec() migration + stale docstrings — CLOSED 2026-08-29
**Owner:** Claude

**Changed:** `db/session.py` binds SQLModel's `AsyncSession` (has `.exec()`); converted all 25 `session.execute(select(...))` sites → `session.exec(...)` with `.scalars().all()→.all()`, `.scalars().first()→.first()`, `.scalar_one_or_none()→.one_or_none()` (publisher `select` import → sqlmodel so exec auto-scalars; the 41 raw `conn.execute` sites untouched). `pyproject`: scoped `error::DeprecationWarning:glitch_signal`. Stale docstrings fixed: `_require_jobs_auth` (said "unset→allow"; fails CLOSED 503), removed dead `config.jobs_auth_token` + wrong comment, documented the MCP default-deny rule in `policy.py` + fixed duplicate `# 3.` numbering.

**Verified:** suite **403 pass**; exec warnings **14→0**, total **31→1** (only third-party aiosqlite ResourceWarnings from test fixtures remain). Live: `/healthz` returns valid queue counts (session.exec().all() works) and the scheduler fires a probe naturally (its 14 session.exec queries work in prod) after the app-wide session-class swap. Prior earlier lifespan part (PR #120) already removed the on_event warnings.

**Audit sweep now 15/18 closed.** Remaining deferred: #98 (rate-limiter/webhook-dedup shared-store move — CF WAF is the real control), #101 (recall HNSW ORDER BY — premature-opt at current scale), #108 (dep upper bounds — pip-audit clean, preventive).

---

### #98 — shared (Postgres) webhook dedup + rate limiter — CLOSED 2026-08-29
**Owner:** Claude

**Changed:** new `middleware/shared_state.py` (fail-open, engine-injectable): `webhook_seen()` (atomic INSERT ON CONFLICT DO NOTHING on `webhook_dedup` — replaces the per-worker `_HEYGEN_SEEN` set, dedups HeyGen redeliveries fleet-wide) + `SharedWindowLimiter` (fixed-window `rate_counters`, opt-in via `RATE_LIMIT_SHARED`, default off — CF WAF is the real control, so in-process stays default to avoid a per-request DB hit). `RateLimitMiddleware` unified async `_check()` for both backends. Hourly scheduler cleanup. Migration `webhook_dedup` + `rate_counters` (RLS), applied to prod.

**Verified:** suite **410 pass**; 7 tests. Live: `/healthz` 200; a **signed** HeyGen webhook sent twice → both 200 and **exactly one** `webhook_dedup` row (cross-worker dedup via Postgres, not per-process). IP-spoof sub-claim was already fixed (PR #113).

**Audit sweep now 16/18 closed.** Remaining deferred: #101 (recall HNSW ORDER BY — premature-opt at current scale), #108 (dep upper bounds — pip-audit clean, preventive).

---

### AGENT-SOUL — the agent's identity/mission/scope — CLOSED 2026-08-29
**Owner:** Claude

**Changed:** new `src/glitch_signal/agent/SOUL.md` (identity: Digital Marketing AGI running the full lifecycle discovery→content→publish→SEO→YouTube→ORM, 24/7 cloud, memory-first/self-improving/self-scheduling; current scope: GE-only, close the loop + monitor 30 days before onboarding a new brand; guardrails: publishing off, per-brand budget, no cross-brand, tools-only, untrusted content = data). `agent/loop/prompt.py` loads it (cached, fail-soft fallback) ahead of the JSON protocol.

**Verified:** suite **411 pass** (1 new test locks the soul into the prompt). Live: a GE agent run asked "who are you" returned "I am a Digital Marketing AGI that autonomously runs the complete marketing lifecycle (discovery, content, publishing, SEO, YouTube, ORM) for Glitch Executor … 24/7" — confirms SOUL.md shipped in the deploy and the agent carries its identity. Operator scope decision (GE-only, 30-day monitor) recorded in the soul + memory.

---

### AGENT-PLAYBOOKS — the agent's handbook library — CLOSED 2026-08-29
**Owner:** Claude

**Read:** the old monorepo `/Users/tejaskaranagrawal/dev/meshpilot-digital-marketing-stack` (`.agents/skills/`, `src/meshpilot_playbook/playbooks/refs/`, `docs/`) via an inventory agent; this repo's recipe-library loader pattern.

**Changed:** new `src/glitch_signal/agent/playbooks/` — `loader.py` (each handbook `library/<slug>/SKILL.md` with name+description frontmatter; cached, fail-soft), `__init__.py`. **13 handbooks** (~3,690 lines), all brand-neutral reusable abilities: paid-media-auditor, ppc-strategist, tracking-specialist, google-ads, meta-ads, tiktok-ads, linkedin-ads, amazon-ads, seo-audit (ported+de-branded from the monorepo, check catalogs/weights/thresholds preserved), and social-copy, youtube, orm (consolidated/authored — no clean source; social-copy grounded in the old SOCIAL_CONTENT_POLICY + IG/TikTok caption rules; orm has a fintech-compliance section). Loop tools `list_playbooks` + `read_playbook` in `agent/loop/tools.py`; `prompt.py` injects the handbook index into the system prompt so the agent reads directly (no list round-trip to loop on). `SOUL.md` gains a "Your handbooks" section.

**Verified:** suite **418 pass** (7 playbook tests). Live: agent reads `social-copy` and produces a TikTok caption following its house-voice rules; a natural caption goal no longer loops on `list_playbooks`. De-brand check clean (no mesh pilot / ai empire / old-repo paths). Framing per operator: these are general agent *abilities* for headless multi-brand operation — GE is the current single run, not the scope of the ability.

**Remains:** the media recipe library (separate, already present) and the playbook library are distinct; a future "skill-workshop" (agent authors its own playbooks) is a possible follow-on (OpenClaw pattern).

---

### CONTENT-POLICY — zero AI footprints in all content — CLOSED 2026-08-29
**Owner:** Claude

**Changed:** new `src/glitch_signal/content_policy.py` — `strip_footprints` (deterministic: em/en/bar dashes + double-hyphen → comma, en-dash number ranges → hyphen, smart quotes + ellipsis-char normalized, seams tidied), `scan_footprints` (flags filler words [leverage/seamless/robust/elevate/unlock/…], "not only…but also", remaining dashes, cliché phrases), `enforce`. Applied in `agent/nodes/caption_writer.py` to the caption + title before storing (both the LLM and human-sheet paths), logging any tells that remain. New loop tool `polish_copy` (mandatory before finalizing content). `SOUL.md` gains a non-negotiable "Content policy — zero AI footprints" section. `prompt.py` gains an anti-repeat rule (don't re-call a tool with the same input) to stop the cheap loop model over-calling verification tools.

**Verified:** suite **431 pass** (13 content-policy tests). Live: an agent caption run used `polish_copy` + consulted `social-copy` and returned a caption with zero em/en-dashes. The deterministic node-gate guarantees the caption pipeline is clean regardless of agent behavior; `polish_copy` + the SOUL rule cover agent-generated content.

**Remains:** the standalone sheet-poster path posts operator-authored captions directly (not through caption_writer) — left unsanitized on purpose (operator authorship); extend if the policy should override human text too. A future publish-time gate would be the single strongest chokepoint once publishing is enabled.

---
### CI-GATEWAY — drift-gated gateway build check + `gateway-production` deploy branch — CLOSED 2026-08-30
**Owner:** Claude (Opus)

> ⚠️ **SUPERSEDED 2026-08-30 (#169):** the `gateway-production` deploy branch described below was **retired** the same day. Railway now deploys the gateway straight from **`production`** via watch paths `gateway/**` — no ff, no separate branch. The drift-gated `gateway` CI job is unchanged and still current; only the deploy-branch/ship-path parts of this entry are obsolete. Do NOT run the "git switch gateway-production…" ship path in **Remains** below.

**Read:** `.github/workflows/ci.yml` (the `changes` drift-filter + api/db/web job pattern), `gateway/{Dockerfile,bridge.py,requirements.txt,railway.json}`, `CLAUDE.md` (branches & promotion), the GATEWAY-1 close on this doc.

**Changed:** `ci.yml` — new `gateway` output on the `changes` job (`^gateway/`), and a drift-gated `gateway` job: `python3 -m py_compile gateway/bridge.py` (catches syntax errors the Dockerfile won't, since it only *runs* bridge.py at container start) + `docker build -t meshpilot-gateway ./gateway` (exactly what Railway builds). CI kept **production-only** on purpose — no second trigger on `gateway-production`. New **`gateway-production`** deploy branch (peer of `web-production`), fast-forwarded from `production`, pushed at the same SHA. Docs: `CLAUDE.md` (Three deploy branches + the CI-runs line + a gateway ship step), `gateway/README.md` (branch-triggered deploy section), lane board.

**Verified:** the PR #148 merge push touched `gateway/README.md`, so it exercised the new job on a real push — CI run 33293681846: `changes` success with `gateway=true`; `api`/`db`/`web` **skipped**; `gateway` **success** (the `docker build` ran green on GitHub's runner); overall **success**. `gateway-production` created and pushed; `git rev-parse` confirms it == `production` (eb5ebc6). Rationale for production-only CI holds: a `gateway-production` ff carries the identical SHA, so Railway's wait-for-CI gates on this same commit's already-green gateway check.

**Remains:** ~~operator sets the Railway service's deploy branch = `gateway-production`; ship path `git switch gateway-production && git merge --ff-only production && git push`~~ — **OBSOLETE (see SUPERSEDED note above).** Actual current state: Railway deploys the gateway from **`production`** (watch paths `gateway/**`, wait-for-CI on, Root Directory `gateway`); ship a gateway change by merging it into `production` — nothing else.

---
### CLAUDE-PLATFORM — Claude best practices in the agent loop — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** platform.claude.com docs (models, prompt-engineering, tool-use, context-mgmt, files) via 6 parallel research agents; `src/glitch_signal/agent/loop/{llm,runner,prompt}.py`, `analytics/cost/pricing.py`, `tests/test_{llm_messages,agent_loop,cost_meter}.py`. Confirmed the loop is JSON-in-text ReAct (`runner.py:30` regex), no native tool use / caching / streaming / stop_reason handling; system prompt (`system_prompt()`) is a stable ~4,260-token prefix (SOUL + protocol + tools + handbook index) with all per-step variables in the user message.

**Changed:** (1) `docs/vendors/anthropic.md` — full runbook (+README index). (2) `llm.py`: default model `claude-haiku-4-5` → **`claude-sonnet-5`**; **stopped forwarding `temperature`** (current-gen 400s; kwarg kept for caption.py back-compat); `max_tokens` 800→2048; **`output_config.effort`** (env `AGENT_LLM_EFFORT`, default `low` — suppresses the thinking block); **prompt caching** — system sent as a `cache_control:{ephemeral}` block; **stop_reason** warnings (max_tokens/refusal/empty) + **Retry-After** honoring (`_retry_delay`). (3) `pricing.py`: Sonnet 5 $2/$10 (was stale $3/$15), Opus 5 $5/$25 (was $15/$75), +Fable 5.

**Verified (live, real Sonnet 5 API w/ the local inference key — "verify against the real dependency"):**
- Old payload with `temperature` → **HTTP 400** (`temperature is deprecated for this model`) — confirmed the latent blocker.
- Real `complete()` path → clean parseable JSON action, no truncation.
- Hardened payload on the **real** system prompt: call-1 `cache_creation_input_tokens=4260`, call-2 `cache_read_input_tokens=4260` (**cache hit**); both `blocks=['text']` (effort=low → no thinking). Suite **451 pass** (local, pre-merge).

**Remains:** **CLAUDE-TOOLS** (biggest pending upgrade) — replace the JSON-in-text ReAct with native tool use (`tools`/`tool_use`/`tool_result`, `strict` schemas, parallel, `stop_reason` loop); then a 2nd cache breakpoint on the last tool def. Later: built-in server tools (web_search/web_fetch/code_exec), Files API for brand PDFs, context editing for long runs. Streaming deferred (small outputs). Also: `pricing.py` `cache_write` models the 5m (1.25×) TTL — if we adopt 1h TTL, that entry needs 2×.

---
### CLAUDE-TOOLS — native tool use for the agent loop — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** `agent/loop/{runner,tools,prompt,llm,policy}.py`, `agent/mcp/client.py`, `tests/test_{agent_loop,agent_mcp,llm_messages,cost_budget,playbooks}.py`. Design: `docs/plans/2026-08-30-claude-tools-native-tool-use.md`.

**Changed:** loop migrated from JSON-in-text ReAct to Anthropic **native tool use**.
- `tools.py`: each of the 11 built-ins gained a JSON-Schema `input_schema`; new `tool_defs()` emits `{name, description, input_schema[, strict]}` (`strict:true` on the closed-schema tools; omitted on free-form ones — generate_media/edit_image/schedule). `tool_descriptions()` removed.
- `mcp/client.py`: `_tools` tuple now carries the tool's `inputSchema` (previously discarded); new `tool_defs()` returns namespaced native defs (no `strict`).
- `llm.py`: extracted shared `_send()` (headers + retry/Retry-After); new **`complete_tools(messages, tools, system, effort)`** → `{content, stop_reason, usage}`, with the cache breakpoint on the **last tool def** (tools cache ahead of system). `complete()`/`complete_messages()` unchanged for the content pipeline.
- `runner.py`: rewritten to the native cycle — maintain a `messages` list, run each `tool_use` block through `policy.allow` → `dispatch` (built-in `execute` or `mcp.call`) → return all `tool_result`s in one user turn (parallel-safe; deny/ERROR → `is_error:true`), loop until `stop_reason != tool_use`; final = `end_turn` text. `parse_action` deleted; loop `__init__` export updated.
- `prompt.py`: dropped the "respond with a SINGLE JSON object" protocol + in-prompt tool list; `system_prompt()` = SOUL + operating rules + handbook index; `build_prompt()` = first user turn.

**Verified:** suite **449 pass** (loop/mcp/cost/playbooks/llm tests rewritten for the native shape). **Live (real Sonnet 5, local key):** (1) raw `complete_tools` — model emitted a `tool_use` block (`recall`, `stop_reason=tool_use`); returning a `tool_result` → `stop_reason=end_turn` text. (2) full `run()` loop with real `complete_tools` + fake `execute` → coherent 1-sentence answer. effort=low kept the turns thinking-free.

**Remains:** built-in **server tools** (web_search/web_fetch/code_execution — web_fetch free, code_exec free when bundled), **Files API** (brand PDFs, workspace-scoped → keep brand→file_id map), **context editing** (`clear_tool_uses_20250919`) for long runs. Optional: `output_config.format` structured outputs for the content nodes; a 2nd MCP cache breakpoint if MCP tool sets grow large.

---
### WEB-TOOLS — web_search + web_fetch (server tools) — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** `agent/loop/{tools,runner}.py`, `analytics/cost/pricing.py`, `tests/test_{agent_loop,cost_meter}.py`. Design: `docs/plans/2026-08-30-web-tools.md`.

**Changed:** added Anthropic **server-side** web tools to the native-tool-use loop.
- `tools.py::server_tool_defs()` — config-gated web_search/web_fetch defs (NOT in the TOOLS registry; Anthropic executes them, so they never hit `execute()`/`policy.allow`). web_search default ON, `max_uses=3`; web_fetch default OFF.
- `runner.py` — `tool_defs = tool_defs() + server_tool_defs() + mcp.tool_defs()`; new **`pause_turn`** branch (a long server-tool turn is re-sent to resume, not treated as final). Server `server_tool_use` blocks aren't dispatched (the existing tool_use filter ignores them); response content is appended verbatim so the `encrypted_content` round-trips.
- `pricing.py` — `anthropic_cost` adds `usage.server_tool_use.web_search_requests × $0.01` (env `COST_ANTHROPIC_WEB_SEARCH_USD`); web_fetch is free. Cost flows into `budget.check` (INC-3).

**Discovery (important):** our Anthropic org is **HIPAA-regulated without Zero Data Retention** → `web_fetch` + `code_execution` return `400 (not available … without Zero Data Retention)`, and the dynamic-filtering `web_search_20260318` auto-provisions code_execution so it's blocked too. **Basic `web_search_20250305` works.** So web_search defaults to that tag and web_fetch defaults OFF (tags overridable via `AGENT_WEB_SEARCH_TAG`/`AGENT_WEB_FETCH_TAG`; flip `AGENT_WEB_FETCH_ENABLED=true` once ZDR is enabled).

**Verified:** suite **452 pass** (server_tool_defs gating for the HIPAA-safe defaults, pause_turn resume, web_search pricing). **Live (real Sonnet 5, local key):** a direct `complete_tools` call ran a real web_search (`server_tool_use`→`web_search_tool_result`→text, `end_turn`), `web_search_requests≥1`, `anthropic_cost≥$0.01`; the full `run()` loop returned a current BTC price; no HIPAA 400 with the basic tag; encrypted round-trip clean.

**Remains:** flip web_fetch (+ code_execution, Files API) on once ZDR is enabled on the org — or move the agent to a non-HIPAA workspace. Consider `response_inclusion` (web_search_20260318) under ZDR for fresher filtering. Files API + context editing are the next capability lanes.

---
### WEB-TOOLS follow-up — moved to a STANDARD (non-HIPAA) Anthropic org — 2026-08-30
**Owner:** Claude (Opus)

**Why:** the agent's original Anthropic org had HIPAA readiness enabled (support@glitchexecutor.com, 2026-08-22, for a no-PHI marketing workload) which hard-blocks web_fetch / code_execution / Files API and is irreversible from the Console. Per platform.claude.com data-retention docs, code_execution + Files API are ineligible under BOTH ZDR and HIPAA — only a standard org unblocks them.

**Changed:** operator provided a new **standard-org** inference key; set as `ANTHROPIC_API_KEY` on **FastAPI Cloud env** (delete+recreate, secret) + local `.env`. `tools.py::server_tool_defs()` — **web_fetch default flipped ON** (was off under HIPAA), docstring de-HIPAA'd; web_search keeps the basic `web_search_20250305` tag by default (dynamic `web_search_20260318` opt-in via AGENT_WEB_SEARCH_TAG — pulls in code_execution + extra rounds = more cost). Docs (`anthropic.md`) + memory updated.

**Verified:** the new key live-accepts web_fetch + code_execution (no HIPAA 400); dynamic web_search + web_fetch both returned real results. Suite green. **Remains:** the merge auto-deploys prod onto the new key + web_fetch on — verify a live Discord run post-deploy. Now-unblocked lanes: **Files API** (brand PDFs), **code_execution** (data crunching).

---
### FILES — brand documents via the Files API — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** `agent/loop/{tools,llm}.py`, `agent/memory/store.py` + `loop/runs.py` (raw-SQL/`_engine` store pattern), `server.py` (`_require_jobs_auth`, `brand_ids`), `supabase/migrations/` (table+RLS pattern), `tests/test_agent_memory.py` (FakeEngine). Design: `docs/plans/2026-08-30-files-brand-documents.md`.

**Changed:** Anthropic Files API wired for per-brand documents.
- `agent/files.py` — thin httpx client: `upload_file(bytes, filename, mime)` (multipart → file record), `delete_file(id)`. GA, no beta header.
- `brand_document` table (migration `20260830180000_brand_document.sql`: brand_id, file_id, filename, mime, size, kind; brand index + file_id unique; RLS enabled) + `agent/documents.py` store (`add`/`list_for_brand`/`delete`, **every query `WHERE brand_id`** — the tenant-isolation guard, since Files API ids are workspace-scoped).
- `server.py` — `POST/GET/DELETE /internal/brand/{brand_id}/documents` (jobs-auth; upload validates brand + PDF/text + ≤25MB → Files API → store row; delete drops the row and the Anthropic file). Added `File`/`Form`/`UploadFile` imports.
- `agent/loop/tools.py` — new **`read_brand_doc(query)`** tool (strict): `documents.list_for_brand(brand)` → document blocks → one bounded `complete_messages()` grounded ONLY in the docs. file_ids come only from the brand's store, never tool input.
- `agent/loop/llm.py::_content_to_anthropic` — pass native `document`/`image` blocks through (was stringifying them).

**Verified:** suite **461 pass** (9 new: files client, store brand-scoping ×3, tool no-docs + block-building, document passthrough). **Live (real Sonnet 5, standard org):** real upload → the REAL `read_brand_doc` path (document block + real `complete_messages`) returned a grounded answer ("forbidden word: unlock; tone: sharp, confident, no hype") → delete. The `brand_document` migration is exercised by CI's from-scratch DB job on push.

**Remains:** agent self-ingest tool (`ingest_brand_doc(url)`), auto-inject the brand doc into the caption pipeline, images via Files API, orphan-file cleanup sweep, optional citations. Operator upload example: `curl -H "x-jobs-token: …" -F file=@brandguide.pdf -F kind=style_guide https://api.meshpilot.app/internal/brand/glitch_executor/documents`.

---
### CONTENT-CLAUDE — content-pipeline text generation on Claude — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** `agent/llm.py` (the MUapi `chat()` shim + all ~10 callers), `agent/nodes/caption_writer.py`, `agent/loop/llm.py` (complete_messages/_apply_effort), `agent/documents.py`, `tests/test_{llm_messages,caption_writer_rules_based,caption_writer_vision,drive_footage_pipeline}.py`. Design: `docs/plans/2026-08-30-caption-claude.md`.

**Changed:** operator directive — MUapi only for image/video, all TEXT to Claude.
- `agent/llm.py`: `chat()` rewritten to route to `complete_messages` (Claude); dropped the `MuapiEngine` text path + `_flatten`. `model_for(tier)`: cheap→`claude-haiku-4-5-20251001`, smart→`claude-sonnet-5` (env `AGENT_CONTENT_MODEL_CHEAP/_SMART`, legacy `AGENT_CONTENT_TEXT_MODEL_<TIER>`). `complete_with_fallback` unchanged. One change moves every text caller (caption_writer, scout, script_writer, text_writer, storyboard, carousel_gen, quote_card, content_router, influencer). **MUapi image/video (`media/generation/`) untouched.**
- `agent/nodes/caption_writer.py`: new `_caption_llm(system, user_text, brand_id)` seam both caption paths call — prepends the brand's uploaded `document` blocks (`documents.list_for_brand`, best-effort) then `chat(tier="smart")` (Sonnet 5). Grounds captions in the real style guide on top of `voice_prompt_path`.
- `agent/loop/llm.py::_apply_effort`: **skip `output_config.effort` for Haiku** — Haiku 4.5 400s on it (a Claude-5-family param). This was breaking every cheap-tier content call.

**Verified:** suite **462 pass** (Claude-routing + Haiku-effort-skip tests; caption tests repointed to the `_caption_llm` seam with the new signature + brand_id). **Live (real API):** `chat([...], tier="cheap")` → Haiku 4.5 returned text; `_caption_llm` (Sonnet 5) with a real uploaded brand guide returned a caption that honored it (avoided the forbidden word "unlock").

**Remains:** structured outputs (`output_config.format`) for guaranteed caption JSON; citations; per-node tier tuning (some nodes may want cheap=Haiku to control cost); consider moving script/text_writer doc-grounding too. Watch content cost (Gemini-flash → Haiku/Sonnet) via the per-brand budget.

---
### DISCOVERY — trending social content via CaptAPI — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** `agent/loop/{policy,tools}.py` (email/publish gate + tool registry), `config.py` (kill-switch flags). Vendor vetting: CaptAPI vs Apify vs Bright Data.

**Changed:** built the agent's discovery ability (operator directive: "build the ability, don't start scraping").
- `agent/discovery/captapi.py` — thin CaptAPI client (`trending(platform,kind,country?,cache=True)` → the endpoint `data`). 5 endpoints wired (IG trending-reels; TikTok trending-feed/popular-hashtags/songs/creators). Bearer `CAPTAPI_KEY`, `cache=true` default (free 24h).
- `agent/loop/tools.py` — `discover_trending(platform,kind?,country?)` tool (+ `_compact_trending`): top-10 items projected to caption/engagement/hashtags/author/url, noisy video/thumbnail-expiry fields dropped.
- `agent/loop/policy.py` — `DISCOVERY_TOOLS={"discover_trending"}` gated by `Policy.discovery_enabled` (from `agent_discovery_enabled`, default **False**) + per-run cap `max_discovery_per_run` (5). Mirrors the email kill-switch — the tool is offered but **DENIED until enabled**, so no external pull happens in the build.
- `config.py` — `captapi_key`, `agent_discovery_enabled=False`, `agent_max_discovery_per_run=5`.
- `CAPTAPI_KEY` stored (FastAPI Cloud env secret + local `.env`); `APIFY_KEY`/`BRIGHTDATA_KEY` in local `.env` for later (unused). Vendor doc `docs/vendors/captapi.md` + README.

**Verified:** suite **470 pass** (8 discovery tests: gate denied-off/allowed-on/per-run-cap, client endpoint-map + request shape + unsupported target, tool compaction + error). The CaptAPI endpoint itself was verified **live during vetting** (200; real US IG trending reels w/ caption/engagement/hashtags) — **no live pull in the build** (gated off, per the operator's "don't scrape").

**Remains:** enable it (`AGENT_DISCOVERY_ENABLED=true` + redeploy) when ready; a scheduled scout node (trending → `Signal` rows) + credit-metering of pulls; Apify/Bright Data for deeper scrapes.

---
### SCOPE — per-run/per-pipeline tool scoping — CLOSED 2026-08-30
**Owner:** Claude (Opus)

**Read:** `agent/loop/{runner,tools,policy}.py`, `server.py` (/internal/agent/run + `_run_agent_bg`), `agent/cron/{service,tool}.py`, `config.py`. Design: `docs/plans/2026-08-30-tool-scoping.md`.

**Why:** the ReAct loop offered `tools.tool_defs()+server_tool_defs()+mcp.tool_defs()` — ALL tools — on every run, so a global kill-switch made a capability usable everywhere at once. For a 24/7 autonomous agent that means "enabled = may act unprompted anywhere." Scoping bounds the toolset to the active job/pipeline.

**Changed:**
- `agent/loop/scopes.py` (new) — `CAPABILITIES` (tool groups incl. `mcp__…*` prefixes) → `SCOPES` (chat/discovery/content/orm/full). `resolve(name)→Scope.allows(tool)` (exact + prefix; unknown→chat). `is_subset(child,parent)` for anti-escalation. `set_current/current` contextvar.
- `runner.run(…, scope="chat")` — `set_current(scope)`; `tool_defs = [d for d in all_defs if scope.allows(d["name"])]`; logs `agent.loop.scope`. **Two layers:** scope=OFFERED, policy=ALLOWED (both must pass); the policy gate is unchanged. Seed recall / episode remember are internal calls, unaffected.
- `server.py` `/internal/agent/run` — reads `scope` (default `agent_default_scope=chat`) → `_run_agent_bg` → run.
- `agent/cron/service.py::_run_agent_turn` — reads `scope` from the job payload → run.
- `agent/cron/tool.py` (schedule) — **anti-escalation:** a self-scheduled `agentTurn`'s scope is clamped to `scopes.current()` unless it's `is_subset` of it. Operator-created cron/REST runs may set any scope.
- `config.py` — `agent_default_scope="chat"`.

**Verified:** suite **476 pass** (6 scope tests: resolve/allows incl. mcp prefix, unknown→chat, is_subset anti-escalation, contextvar, runner filters offered tools chat vs content, default=chat). **Live:** real loop with `scope="chat"` → `agent.loop.scope offered=6 scope=chat total=15` and a coherent answer; filter correct (chat ✗ generate_media; content ✓ generate_media, ✗ discover_trending).

**Remains:** per-channel Discord scope mapping; env/per-brand scope-registry override; then define the actual pipelines (discovery/content/orm scheduled runs) that use the broader scopes. Enablement is now enforceable: build tool (policy-gated off) → define pipeline+scope → enable the kill-switch.

---

## PIPELINE — deliberate scoped/scheduled runs (2026-08-30)

**Read:** the SCOPE "Remains" above (defines this lane); `scopes.py`, `runner._run_agent_bg`, `cron/{store,schedule,service}.py`, `policy.py`.
**Changed:**
- `agent/loop/pipelines.py` (new) — declarative registry (mirrors scopes.py). `Pipeline(name, scope, goal, max_steps, schedule_kind, schedule, requires)` + `render_goal(brand)` (templates `{brand}`) + `missing_requirements()` (required flags currently off). `registry()`/`resolve()`/`names()`. Three pipelines: **discovery** (scope=discovery, requires `agent_discovery_enabled`, daily 13:00Z), **content** (scope=`content_draft` caption-first, or `content` when `agent_content_media_enabled`, daily 14:30Z), **orm** (scope=orm, daily 15:00Z). Every goal ends with an explicit no-effect boundary.
- `agent/loop/scopes.py` — new scope `content_draft` = memory+knowledge+quality (caption-first content, no paid media).
- `config.py` — `agent_content_media_enabled=False` (content pipeline media opt-in).
- `server.py` — `POST /internal/agent/pipeline/{name}` (resolve → 409 on missing `requires` → `_run_agent_bg` with the pipeline's scope+goal+max_steps) and `POST /internal/agent/pipeline/{name}/schedule` (seed a `payload_kind=agentTurn` cron job at the cadence; 409 while `agent_cron_enabled` off).

**Invents no new gate** — composes SCOPE (offer+dispatch, enforced both since #163) + policy (publish/discovery default-off → drafts/notes only) + the self-schedule clamp (cron.tool, unchanged).

**Verified:** suite **486 pass** (9 pipeline tests: registry/resolve, every scope resolves exactly, goals template + carry a boundary, schedules validate against the scheduler, discovery requires its flag, content caption-first vs media opt-in). Endpoint validation smoke via TestClient: unknown→**404**, discovery-while-gated→**409**, no-auth→**401** (the one `/schedule` 200 wrote a stray `pipeline:content` row to the shared DB — since this local `.env` has `AGENT_CRON_ENABLED=true` + a live Supabase URL — and was deleted; shipped default is `False`).

**Ships inert:** manual endpoint operator-initiated; scheduled jobs need `agent_cron_enabled`; discovery needs `agent_discovery_enabled`; real content media needs `agent_content_media_enabled`. All default False.

**Remains:** live operator smoke of a real content run → review drafts; publish path is a separate, deliberate decision; per-brand cadence overrides; the review-fixes lane (#163) already closed the SCOPE dispatch-bypass + discovery Qodo findings.

### PIPELINE review-fixes (#164 Qodo) — 2026-08-30
Five valid findings on #164, all fixed:
- **[HIGH/security] cross-brand auth** — both endpoints read `brand` from the body while `_require_jobs_auth` validates the *query* brand → default-brand token could target any brand. Now brand comes from `?brand=` (the authorized brand); body brand ignored. ⚠️ **Pre-existing:** the older `/internal/*` endpoints (`agent/run`, `curate`, `remember`, …) share this body-brand pattern — a separate hardening lane (task flagged).
- **[HIGH/correctness] scheduled `requires` bypassed + [HIGH] media opt-out ineffective** — same root cause: the seed froze the resolved goal+scope into the cron payload. Now the payload carries **only the pipeline name**; new `cron.service._run_pipeline_turn` re-resolves the pipeline live each fire — checks `missing_requirements()` (SKIPs, recorded not executed, if unmet) and reads the current `agent_content_media_enabled`. New `payload_kind="pipelineTurn"`.
- **[MED/reliability] re-seed 500** — `create_job` is insert-only vs the unique `(brand_id,owner,name)` index. Schedule is now idempotent: find existing job via `list_jobs` → `update_job` (enable+reschedule) or create; returns `created`.
- **[MED/reliability] non-object JSON 500** — dropped body-parsing from the manual endpoint (brand now from query); schedule likewise reads no body.
**Verified:** suite **494 pass** (+8: `_run_pipeline_turn` skip/re-resolve/unknown; TestClient body-brand-ignored, pipelineTurn name-only seed, idempotent re-seed→update, cron-off 409 — all DB-mocked). Design doc updated.

### SEC-BFLA review-fixes (#166 Qodo) — 2026-08-30
Four valid findings on #166 (the internal-surface BFLA sweep), all fixed here (coordinated with the peer session that owned #166 — it was done, not touching server.py):
- **[HIGH/security] fb/ig publishing BFLA still open** — `/internal/{facebook,instagram}/test-post` take their target from body **`brand_id`** (a different key than the swept `brand`), so #166 missed them and a token for brand A could still publish as brand B. Now both derive the target from `_authorized_brand(request, {"brand": body.get("brand_id")})` → authorized `?brand=`, mismatched `brand_id` → 400.
- **[HIGH/correctness] configured default brand rejected** — `_authorized_brand` defaulted to the literal `"glitch_executor"` while `_require_jobs_auth` authenticates against `settings().default_brand_id`; a non-`glitch_executor` deployment would 400 every authenticated no-`?brand=` call. Now uses `settings().default_brand_id`. Same literal in `internal_agent_pipeline{,_schedule}` fixed by routing them through `_authorized_brand` too.
- **[HIGH/correctness] gateway regression** — the Discord bridge sent `MESHPILOT_BRAND` only in the body; with the new query-brand contract a non-default brand would 401/400. `gateway/bridge.py` now sends `params={"brand": BRAND}` on both the run POST and the poll GET.
- **[MED/docs] stale docstrings** — 8 `/internal/*` Body: lines synced to the "brand via `?brand=`, body must match" contract.
**Verified:** suite **505 pass** (+4 in test_internal_brand_auth: fb/ig body-`brand_id` can't override + publishes as authorized brand; `_authorized_brand` uses the configured default not a literal). Gateway `py_compile` OK.

---
