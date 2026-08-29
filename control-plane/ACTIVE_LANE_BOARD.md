# Active Lane Board

> The single live queue. Lanes move: OPEN → CLAIMED → IN PROGRESS → IN VERIFICATION → CLOSED.
> Format + rules: see docs/LANE-LIFECYCLE.md.

## Active

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

### DB-OPT — optimize the schema for the current workflow (drop old-SaaS tables)          [OPEN]
Owner: unassigned        Opened: 2026-08-28
Reading: docs/plans/2026-08-28-phase1-source-to-publish.md, src/glitch_signal/db/models.py, alembic/versions/
Acceptance: schema holds only what source→publish needs; orphaned old-SaaS tables (ORM: comment_reply/strategic_reply/mention_event/orm_response; + whatever else the pruned code no longer uses — video/scout/metrics pending the AI-generation scope call) dropped via one consolidation migration; migration app-driven; app boots; /healthz 200.
Write-back: ARCHITECTURE.md (data model), control-plane/ENGINEERING_SUPERVISOR.md
Notes: The 14 tables were copied from the old Mesh Pilot SaaS. Schema FOLLOWS code — do this AFTER PRUNE-1/VENDOR-1 remove the subsystems. Open scope question: does the current workflow include AI content GENERATION (scout→LLM→video) or ONLY source→publish of provided content? That decides whether signal/scout_checkpoint/video_asset/video_job stay.

## Recently closed

- **GE-1 — per-brand `GE_` env resolver + Facebook publisher** (2026-08-28) — per-brand resolver + Meta FB publisher live; real FB post verified; GE_JOBS_AUTH_TOKEN gate enforced. → supervisor

- **DEPLOY-1 — resolve `upload-post` private dep + first FastAPI Cloud deploy** (2026-08-28) — live + /healthz 200 at meshpilot-social-media-agent.fastapicloud.dev; DB migrated (us-east-2). → supervisor

- **SETUP-1 — Bootstrap: standalone extraction + FastAPI Cloud wiring + GE brand creds** (2026-08-28) — extracted `glitch_signal` into a standalone repo, decoupled from the monorepo, linked to the FastAPI Cloud app, staged GE brand credentials. → supervisor
