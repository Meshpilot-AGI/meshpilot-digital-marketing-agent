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

### AP — AyurPet (registered 2026-09-12, ARMED 2026-09-12 — daily Drive-to-social)
Natural Ayurvedic pet care for dogs — a **Shopify** store at https://theayurpet.com. `env_prefix: AP`.
**The content is not generated.** `content_source: drive_footage`: the videos already exist in the
Drive folder `AutoPosting_Social_AyurPet` (`AP_DRIVE_FOLDER_ID`), shared Viewer with MeshPilot's own
SA `meshpilot-agent@capable-boulder-487806-j0.iam.gserviceaccount.com` (the unprefixed
`GOOGLE_DRIVE_SA_JSON`; GE keeps its own `GE_GOOGLE_DRIVE_SA_JSON`). The `drive_to_social`
capability posts one video per run, oldest by name, to Instagram Reels (`AP_META_*`) and TikTok
(Buffer channel `theayurpetstore`, `AP_BUFFER_API_KEY`) together, with an agent-written caption in
brand voice, and records the outcome per platform in `drive_post` so nothing posts twice.
Schedule: cron job `066773bf` — `30 10 * * *` America/New_York. First real post 2026-09-12 (file
`11` → IG reel DdNRC2Vk8EQ + Buffer TikTok 6aa5ed4c…). Operator token `AP_JOBS_AUTH_TOKEN`
(rotated 2026-09-12; `?brand=ayurpet`).
Every post is also appended to the operator sheet `AP_POSTING_SHEET_ID` (Sheet1, legacy columns +
`instagram_url`) — the DB row is the idempotency record, the sheet is for humans.
History: before the refactor the same job ran TikTok-only from a tracking sheet
(`AyurpetTiktok Posting - Task #2`, 49 posted Apr 20 – May 9 2026); the 28 of those still in the
folder were seeded into `drive_post` so the agent starts on the 84 fresh files.
`seo.publisher: shopify` — the git-repo SEO publisher does not apply, and a Shopify Admin API
publisher does not exist yet. ORM guardrails are pet-HEALTH-shaped (no "cures / treats / FDA
approved / vet recommended") and more conservative than GE's: `neutral_technical` goes to review,
because a question about a supplement is a health question.

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
   ⚠️ **That file is gitignored and never reaches production.** The directory was designed as a
   nested private repo on a box that no longer exists; the runtime is FastAPI Cloud and this repo
   is public. GE ran on the built-in default the whole time for exactly this reason. The path that
   reaches prod is **`BRAND_CONFIGS_JSON`** in the cloud env — a JSON object keyed by brand_id
   holding every brand's config. Rebuild it from the local files and set it (`env set` is
   create-only: delete first to update):
   ```
   python -c 'import json,pathlib; print(json.dumps({p.stem: json.load(open(p)) for p in pathlib.Path("brand/configs").glob("*.json")}, separators=(",",":")))' \
     | uvx --from "fastapi[standard]" fastapi cloud env set BRAND_CONFIGS_JSON --value-stdin
   ```
   Adding a brand file WITHOUT the default brand's file crashes the API at boot — materialise both.
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
