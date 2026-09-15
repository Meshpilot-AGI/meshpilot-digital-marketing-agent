# MeshPilot job submitter (Railway)

The **only** container in this system with a browser. It drains job applications the operator has
approved in Discord and drives the ATS's public application form.

## Why it is a separate Railway service

Neither Greenhouse nor Lever exposes a candidate-side application API — both application POSTs
require the **employer's** key — so a candidate must drive the public web form. That needs a browser,
and the API runs on FastAPI Cloud, which builds from Python standards with no way to install
Chromium's system libraries. Railway takes an arbitrary Dockerfile, and the gateway already lives
there, so the browser lives here.

The image is `mcr.microsoft.com/playwright/python`, which ships Chromium **and** its system deps —
rather than an apt incantation that drifts out of date silently.

## Deploy model — git is the source of truth

Same as `gateway/`: the service is connected to
`Meshpilot-AGI/meshpilot-digital-marketing-agent` @ **`production`**, so merging a PR into
`production` is the ship. **Never `railway up` from a laptop** — a CLI-uploaded image is not in git,
and the next git-triggered build silently reverts it. That is exactly the drift this model prevents.

Build settings:

| Setting | Value | Why |
|---|---|---|
| Source | GitHub repo @ `production` | git is truth, same as the gateway |
| `RAILWAY_DOCKERFILE_PATH` | `submitter/Dockerfile` | the build context is the repo ROOT — the Dockerfile `COPY src ./src` and installs the agent package |
| Watch paths | **deliberately UNSET** | see below |

### Why watch paths are unset (and the gateway's are not)

The gateway watches `gateway/**` because it is self-contained: one `bridge.py` and its requirements.

The submitter is **not** self-contained. It installs the agent package, so its behaviour depends on
`src/glitch_signal/**` and `pyproject.toml` as much as on `submitter/**` — the submission guards, the
fact verifier and the store all live there. A watch path of `submitter/**` would mean a change to
those guards **never redeploys the submitter**, leaving the one process that can send an application
running an older copy of the rules than the rest of the system believes is in force.

So the submitter rebuilds on every push to `production`. That costs extra builds and guarantees it
never runs stale guard code. If the build noise ever matters, the correct watch set is
`submitter/**` + `src/**` + `pyproject.toml` — never `submitter/**` alone.

## Environment

| Var | Notes |
|---|---|
| `MESHPILOT_BRAND` | `tejas` |
| `BRAND_CONFIGS_JSON` | the brand registry — brand config FILES are gitignored, so this env var is the only source that reaches any container |
| `DATABASE_URL` | Supabase Postgres. **Operator-supplied** — it is a secret in FastAPI Cloud and cannot be read back |
| `DISCORD_BOT_TOKEN` | copied from the gateway service |
| `SUBMITTER_LIVE` | **must be exactly `true` to send.** Unset / `1` / `yes` are all dry runs |
| `SUBMITTER_POLL_SECONDS` | loop cadence (default 300) |
| `SUBMITTER_MAX_PER_RUN` | ceiling per pass (default 1) |

## Three switches, all required, before anything is sent

1. the operator reacted ✅ on the Discord card (status `approved`/`edited`),
2. the policy gate allows it (`agent_jobs_enabled` + `agent_job_apply_enabled` + the publish
   kill-switch + the 3/day cap),
3. `SUBMITTER_LIVE=true` in this container.

Any one of them off means the pass is a dry run: the form is filled and screenshotted, and nothing is
submitted. The redundancy is deliberate — the irreversible step should take more than one mistake.

## Known limit

**Lever's apply form serves reCAPTCHA**, so the CAPTCHA hard-stop fires on every Lever posting and
they come back `manual_required`. Greenhouse is the only working auto-submit path today. See
`agent/jobs/drivers/browser.py` for why that may be over-cautious and what would settle it.
