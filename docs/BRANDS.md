# Brand Guide — the agent's brand registry

The list of **projects (brands)** this agent serves, and how each is wired. This
is the agent's reference for who it works for: every onboarded brand appears
here with its tag and status. See `docs/VISION.md` for the Projects × Capabilities
model and the per-brand principle.

## The model in one line

A brand is a tenant with its **own** keys. Each declares an **`env_prefix`** (its
tag) in its brand config; every credential resolves as `<TAG>_<KEY>` via
`config.brand_env` — there are **no global keys**. `brand_id` is the config
identifier (snake_case); the tag is the short env prefix.

## Onboarded brands

| Tag | Brand | `brand_id` | Status | Capabilities live |
|-----|-------|-----------|--------|-------------------|
| **GE** | **Glitch Executor** | `glitch_executor` | live | Facebook (Meta) ✅, YouTube ✅, Buffer (TikTok/X/LinkedIn) ✅ |

### GE — Glitch Executor
The first brand/tenant. `env_prefix: GE`, so its keys are `GE_*`.

- **Meta (Facebook / Instagram):** FB Page `1120765137796667`, IG user
  `17841468194646846`. Publishing verified live (a real post to the FB page).
- **YouTube:** channel **Glitch Executor** (`UCky5yKjfKsEPb2K0ePZA-yw`), connected
  via OAuth2 (a service account can't reach a channel). Consent done; encrypted
  refresh token stored in `PlatformAuth`; full scopes (upload + manage + force-ssl).
  Re-consent at `/oauth/youtube/start?brand=glitch_executor`; verify at
  `/internal/youtube/whoami`. Keys: `GE_YOUTUBE_CLIENT_ID` / `GE_YOUTUBE_CLIENT_SECRET`.
- **Keys (names only; values in the cloud env / gitignored local `.env`):**
  `GE_META_APP_ID`, `GE_META_APP_SECRET`, `GE_SYSTEM_USER_TOKEN`,
  `GE_META_PAGE_ID`, `GE_META_IG_USER_ID`, `GE_BUFFER_API_KEY`,
  `GE_GOOGLE_DRIVE_SA_JSON` (Google SA, project `cs-poc-dgkx8nmsfqkufgysguvfktq`),
  `GE_JOBS_AUTH_TOKEN` (gates `/jobs/*` + `/internal/*`).

## Onboarding a new brand

1. **Pick a tag** — a short UPPERCASE prefix (e.g. `ACME`), unique across brands.
2. **Add a brand config** — `brand/configs/<brand_id>.json` with
   `"env_prefix": "<TAG>"` (validated against `brand/schema/brand.config.schema.json`).
3. **Set its keys** in the **cloud env** (source of truth) as `<TAG>_<KEY>` — the
   same key names GE uses (Meta app/token/page/IG, Buffer, Google SA, jobs token).
   Never set global/unprefixed keys.
4. **Connect platforms** — Meta app + system-user with publish access to the
   brand's page; Buffer channels; a Google SA with Drive access; etc.
5. **Verify** by triggering a post from the deployed app (per the runs-on-app
   rule), then add the brand to the table above.

## Notes

- Infra keys are **not** brand-scoped and stay global: `DATABASE_URL` /
  `SIGNAL_DB_URL` (Postgres), `SUPABASE_*`, `LOGFIRE_TOKEN`, `SENTRY_DSN`,
  `MUAPI_KEY`, and `AUTH_ENCRYPTION_KEY` (Fernet — encrypts OAuth tokens at rest
  + signs state tokens; **keep stable**, rotating it invalidates stored tokens).
- Google SA on the cloud must be **inline JSON** (`from_service_account_info`),
  not a file path — see the runs-on-app note in memory / `docs/VISION.md`.
