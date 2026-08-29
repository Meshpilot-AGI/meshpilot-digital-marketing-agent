# Active Lane Board

> The single live queue. Lanes move: OPEN → CLAIMED → IN PROGRESS → IN VERIFICATION → CLOSED.
> Format + rules: see docs/LANE-LIFECYCLE.md.

## Active

### GE-1 — per-brand `GE_` env resolver + Facebook publisher          [IN PROGRESS]
Owner: Claude        Opened: 2026-08-28
Reading: ARCHITECTURE.md, docs/DOC-SYSTEM.md, src/glitch_signal/config.py, src/glitch_signal/platforms/
Acceptance: a per-brand env resolver reads `GE_<KEY>` for the active brand (brand_id `glitch_executor`, tag `GE`); a Facebook publisher posts a text update to the GE page using `GE_META_APP_ID` / `GE_META_APP_SECRET` / `GE_SYSTEM_USER_TOKEN`; unit test green; one real post verified.
Write-back: ARCHITECTURE.md (env convention + FB publisher), control-plane/ENGINEERING_SUPERVISOR.md
Notes: creds already staged in local .env and the FastAPI Cloud app env (all `GE_`-prefixed). No code reads them yet — this lane wires them.

### BUFFER-1 — extend Buffer publisher to X + LinkedIn          [OPEN]
Owner: unassigned        Opened: 2026-08-28
Reading: ARCHITECTURE.md, src/glitch_signal/platforms/buffer.py
Acceptance: buffer.publish() supports x + linkedin (not just tiktok); reads the Buffer token (reconcile `BUFFER_API_TOKEN` vs the cloud-set `GE_BUFFER_API_KEY`); a scheduled post reaches X and LinkedIn via Buffer; NotImplementedError paths removed for those targets.
Write-back: ARCHITECTURE.md (Buffer platform matrix + token env name), control-plane/ENGINEERING_SUPERVISOR.md
Notes: today buffer.py hard-codes tiktok-only (raises NotImplementedError otherwise); X not in its platform map.

### PRUNE-1 — remove ORM / comment-engagement subsystem          [OPEN]
Owner: unassigned        Opened: 2026-08-28
Reading: docs/plans/2026-08-28-phase1-source-to-publish.md, src/glitch_signal/comments/, src/glitch_signal/orm/, src/glitch_signal/scheduler/queue.py
Acceptance: comments/ + orm/ + x-engagement (x_sweeper, integrations/x engagement use) removed; scheduler ORM ticks removed from queue.py; app imports + boots; /healthz 200; suite green. Independent of GE-1/BUFFER-1 — safe deletion.
Write-back: ARCHITECTURE.md, control-plane/ENGINEERING_SUPERVISOR.md
Notes: Phase 1 is source→publish only; engagement is out of scope (see plan).

### VENDOR-1 — remove Upload-Post + redundant direct integrations; re-point sources          [OPEN]
Owner: unassigned        Opened: 2026-08-28
Reading: docs/plans/2026-08-28-phase1-source-to-publish.md, src/glitch_signal/platforms/, src/glitch_signal/sheet_posting/, src/glitch_signal/agent/nodes/publisher.py
Acceptance: platforms/upload_post.py + webhooks/analytics/onboarding upload_post removed; tiktok/twitter/instagram + integrations/linkedin removed; orphaned TikTok OAuth removed; publisher.py + _PUBLISH_PRIORITY route only to Buffer/Meta/YouTube; DB scheduler + sheet_posting publish through them; suite green; a real post verified per platform.
Write-back: ARCHITECTURE.md, control-plane/ENGINEERING_SUPERVISOR.md
Notes: BLOCKED until GE-1 + BUFFER-1 land (can't re-point onto Buffer/Meta until they can do the job). Keep platforms/youtube.py.

## Recently closed

- **DEPLOY-1 — resolve `upload-post` private dep + first FastAPI Cloud deploy** (2026-08-28) — live + /healthz 200 at meshpilot-social-media-agent.fastapicloud.dev; DB migrated (us-east-2). → supervisor

- **SETUP-1 — Bootstrap: standalone extraction + FastAPI Cloud wiring + GE brand creds** (2026-08-28) — extracted `glitch_signal` into a standalone repo, decoupled from the monorepo, linked to the FastAPI Cloud app, staged GE brand credentials. → supervisor
