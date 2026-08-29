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

## Migrations (app-driven — never from a laptop in normal ops)
Alembic; `alembic/env.py` uses `settings().resolved_db_url()` + `db_connect_args()`
and feeds the URL straight to the engine (a `%`-encoded password breaks alembic's
configparser interpolation). Ordering: **additive migrations before deploy,
removals after**.
```bash
uv run alembic upgrade head      # bootstrap / emergencies only
```

### CI migrations (GitHub Actions — the normal path, not the Mac)
`.github/workflows/db-migrate.yml` runs `alembic upgrade head` against the
production DB when migrations land on `production` (paths `alembic/**`) or on
manual `workflow_dispatch`. The GitHub runner is IPv4 → reaches the session
pooler. DSN is the repo secret **`SIGNAL_DB_URL`** (session pooler, us-east-2).
`upgrade head` is idempotent, so re-runs are safe no-ops.

**PR gate** — `.github/workflows/db-migrate-check.yml` runs on any PR that
touches `alembic/**` or `db/**`: it spins up a throwaway Postgres, applies the
full migration chain from scratch (`alembic upgrade head`), and flags model
drift (`alembic check`, informational). A broken migration fails the PR — never
production. Never touches the real Supabase DB.

**Ordering** (the app auto-deploys on the same production push):
- **Additive** migration (new column/table the new code uses) → backward-compatible,
  fine to run alongside the deploy.
- **Removal** → ship the code first, then run this via `workflow_dispatch` **after**,
  so you never drop something the running code still reads.

> Not Supabase Branching (yet): that expects Supabase-CLI SQL migrations in
> `supabase/migrations/` + `config.toml`. We use Alembic, so the "Supabase
> Preview" check skips (harmless). **DECIDED 2026-08-28:** we adopt Supabase-native
> SQL migrations + enable Branching (preview DBs) **as part of DB-OPT**, when the
> lean schema is rewritten — retiring Alembic + `db-migrate*.yml` in one clean
> move, rather than doing it now and re-churning it.

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
