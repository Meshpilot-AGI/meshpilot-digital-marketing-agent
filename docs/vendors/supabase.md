# Vendor runbook — Supabase (Postgres + Storage)

Our database **and** media store. Operating guide; validate against
https://supabase.com/docs/guides/database/connecting-to-postgres when unsure.

## Our setup
- Project ref: **`qkztphfjwgluwwlgeyys`**, region **us-east-2**.
- The app connects via the **session pooler** (IPv4). The direct host
  `db.<ref>.supabase.co` is **IPv6-only** and unreachable from most networks —
  do not use it.
- Runtime DSN is a cloud env secret **`SIGNAL_DB_URL`** (takes precedence over
  Supabase's `DATABASE_URL`).

## Connection string (session pooler, port 5432)
```
postgresql+asyncpg://postgres.<ref>:<url-encoded-password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```
- User is **`postgres.<ref>`** (not bare `postgres`) for the pooler.
- URL-**encode the password** (`@`→`%40`, `^`→`%5E`, …).
- Port **5432** = session pooler (prepared statements OK — use for migrations +
  a persistent app). Port **6543** = transaction pooler (pgbouncer; serverless).

## How the code handles it (config.py)
`resolved_db_url()` + `db_connect_args()`:
- Normalize `postgres://`/`postgresql://` → **`postgresql+asyncpg://`**.
- `ssl="require"` — Supabase's pooler presents a **self-signed root**, so full
  verification (`ssl=True`) fails; `require` = encrypt without cert verify.
- `statement_cache_size=0` for the pgbouncer pooler (`pooler.supabase.com` / :6543).
- Requires **`greenlet`** (SQLAlchemy async).

## Migrations — Supabase-native (Alembic retired 2026-08-29)

DB changes are **SQL migration files** in `supabase/migrations/*.sql`, pushed to
Supabase by the **Supabase GitHub integration** when they land on `production`.
`supabase/config.toml` pins the project (`qkztphfjwgluwwlgeyys`, PG major 17).
The app still *connects* via `SIGNAL_DB_URL` (asyncpg) — only the migration
mechanism changed; Alembic (`alembic/`, `db-migrate*.yml`) is gone.

**Baseline:** `supabase/migrations/20260829054500_init_schema.sql` — the schema
generated from `glitch_signal.db.models`, written **idempotent** (`CREATE TABLE/
INDEX IF NOT EXISTS`, `ENABLE ROW LEVEL SECURITY`) so it is a safe no-op on the
existing prod DB and builds fresh preview/shadow DBs from scratch. (The old
`alembic_version` table lingers harmlessly; drop it whenever.)

**Add a change:** write a new `supabase/migrations/<timestamp>_<name>.sql` (plain
SQL). Make it forward-only and, where sensible, idempotent. Merge to `production`
→ the integration applies it; the "Supabase Preview" check applies it to a shadow
DB on PRs. Ordering still holds: **additive before the code deploys, removals after.**

**CI check:** the `db` job in `.github/workflows/ci.yml` (fires on `supabase/
migrations/**` or `db/**` drift) spins up a throwaway Postgres and applies every
migration from scratch with `psql -v ON_ERROR_STOP=1`, then re-applies to prove
idempotency. Never touches the real DB.

> ⚠️ CLI note: the local `supabase` CLI must be logged into the **Meshpilot**
> Supabase account to `link`/`db pull` this project. The MCP server is the
> reliable path for schema reads/one-off SQL against prod.

## Storage — per-brand media buckets (STORAGE-1)

Generated media is persisted to Supabase **Storage** because muapi's
`cdn.muapi.ai` URLs expire (~30 days). Each brand has its **own** bucket
`<env_prefix>-media` (GE → **`ge-media`**), overridable via the brand config's
`media_bucket`. Public buckets (the media is destined for public social posts,
and publishers must fetch it) — switch to private + signed URLs later if needed.

- **Code:** `src/glitch_signal/media/generation/storage.py` — `bucket_for()`,
  `ensure_bucket()` (idempotent create), `persist(asset, brand)` (download the
  engine URL → upload to `<bucket>/<recipe>/<uuid>.<ext>` → rewrite the Asset URL
  to the durable Supabase public URL; muapi URL kept in `metadata.source_url`).
- **Auth:** the Storage REST API with the **service key** `SUPABASE_SECRET_KEY`
  (`Authorization: Bearer` + `apikey`), over httpx — no supabase-py dep.
  ```
  create : POST {SUPABASE_URL}/storage/v1/bucket            {"id","name","public"}
  upload : POST {SUPABASE_URL}/storage/v1/object/{bucket}/{path}   raw bytes, x-upsert:true
  public : GET  {SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}
  ```
- **Wiring:** `/internal/media/generate` persists by default (opt out `store:false`)
  and returns `{url (Supabase), source_url (muapi), bucket}`. `POST
  /internal/media/ensure-bucket {brand}` pre-creates a bucket.
- Verified 2026-08-29: `ge-media` created; a generated logo lands at
  `…/object/public/ge-media/muapi-logo-creator/…png` → HTTP 200 image/png.

## Gotchas we hit
- Direct `db.<ref>.supabase.co` failed with `nodename nor servname` (IPv6-only).
- `ssl=True` → `CERTIFICATE_VERIFY_FAILED: self-signed certificate`.
- Wrong region pooler → `Tenant or user not found` (ours is us-east-2).
- `%` in the DSN → alembic `configparser` interpolation error.
