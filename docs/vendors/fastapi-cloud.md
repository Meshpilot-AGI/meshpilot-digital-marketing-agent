# Vendor runbook — FastAPI Cloud

Our deploy platform. This is our operating guide; validate against the official
docs at https://fastapicloud.com/docs when in doubt.

## Our setup
- Account/team: **`helpn8nworld`** ("Mesh Pilot"), user `help.n8nworld@gmail.com`.
- App: **`meshpilot-social-media-agent`**, id `0d017e5b-1834-4952-8a77-b68f83ff2bfc`, us-east-1.
- URLs: `https://api.meshpilot.app` (custom domain) + `…fastapicloud.dev`.
- Deploy branch: **`production`** (the GitHub default branch). GitHub App connected.

## CLI (via uvx — nothing installed globally)
```bash
uvx --from "fastapi[standard]" fastapi cloud <cmd>
```
Auth: local `.env` `FASTAPI_CLOUD_TOKEN` (app-scoped deploy token) for `deploy`;
the interactive `auth login` session for `env`/admin. `whoami`, `apps get <id>`,
`link <id>`, `logs --no-follow --since 15m`.

## Deploy
- **Auto (normal):** merge to `production` → the GitHub App auto-deploys. **Only
  the default branch deploys** — other branches/PRs are ignored (no previews).
- **Manual (testing):** `fastapi cloud deploy .` from the repo (uses the token).

## Env vars = runtime source of truth
```bash
fastapi cloud env list --path . --json
printf '%s' "$VAL" | fastapi cloud env set NAME --value-stdin --secret --path .   # secrets via stdin
fastapi cloud env set NAME VALUE --path .                                          # non-secret
fastapi cloud env delete NAME --yes --path .
```
The CLI never prints secret values. Local `.env` is NOT read by the cloud.

> ⚠️ **`env set` only CREATES — it will NOT UPDATE an existing var.** Re-running
> `env set NAME …` on a var that already exists silently no-ops (its `updated_at`
> never moves), leaving the old/blank value. This cost us hours on a blank
> `GE_BUFFER_API_KEY`. **To change an existing value: `env delete NAME --yes`,
> then `env set` fresh.** Confirm with `env get NAME --json` that `updated_at`
> moved. Env changes only reach the running app after a **redeploy**.

## Hard-won gotchas (all cost us a broken deploy once)
- **`fastapi[standard]` is required**, not bare `fastapi` — the runtime launches
  via the `fastapi run` CLI, which lives in that extra. Bare `fastapi`
  crash-loops: `RuntimeError: please install "fastapi[standard]"`.
- **`greenlet`** must be an explicit dep (SQLAlchemy async needs it; not
  auto-installed on every arch).
- **`🚀 Build complete!` ≠ healthy.** The build can succeed while the app
  crash-loops. Always verify `/healthz` 200 + `fastapi cloud logs` after deploy.
- **No managed DB, no migration hook.** Use an external Postgres (Supabase) and
  run migrations app-side (see supabase.md).
- The entrypoint is `main.py` (`main:app`); Logfire is wired there behind
  `LOGFIRE_TOKEN` (injected by the Logfire integration).

## Verify
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.meshpilot.app/healthz
uvx --from "fastapi[standard]" fastapi cloud logs --no-follow --since 15m
```
