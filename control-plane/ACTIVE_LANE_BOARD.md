# Active Lane Board

> The single live queue. Lanes move: OPEN → CLAIMED → IN PROGRESS → IN VERIFICATION → CLOSED.
> Format + rules: see docs/LANE-LIFECYCLE.md.

## Active

### GE-1 — per-brand `GE_` env resolver + Facebook publisher          [OPEN]
Owner: unassigned        Opened: 2026-08-28
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

### DEPLOY-1 — resolve `upload-post` private dep + first FastAPI Cloud deploy          [IN PROGRESS]
Owner: Claude        Opened: 2026-08-28
Reading: pyproject.toml, README.md, .fastapicloudignore
Acceptance: `uv sync` resolves with no access to a private fork (vendor it, make it an optional extra, or grant build access); `fastapi deploy` to app meshpilot-social-media-agent succeeds and the URL serves; `/healthz` returns 200.
Write-back: README.md (deploy notes), control-plane/ENGINEERING_SUPERVISOR.md
Notes: blocker = `upload-post @ git+https://github.com/glitch-exec-labs/upload-post-pip.git@main`. Also needs an external Postgres (Supabase/Neon) + `SIGNAL_DB_URL` before boot succeeds.

## Recently closed

- **SETUP-1 — Bootstrap: standalone extraction + FastAPI Cloud wiring + GE brand creds** (2026-08-28) — extracted `glitch_signal` into a standalone repo, decoupled from the monorepo, linked to the FastAPI Cloud app, staged GE brand credentials. → supervisor
