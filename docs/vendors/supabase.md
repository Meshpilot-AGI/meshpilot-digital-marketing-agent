# Vendor runbook — Supabase (Postgres)

Our database. Operating guide; validate against
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
uv run alembic upgrade head      # bootstrap only; prefer an app-side trigger
```

## Gotchas we hit
- Direct `db.<ref>.supabase.co` failed with `nodename nor servname` (IPv6-only).
- `ssl=True` → `CERTIFICATE_VERIFY_FAILED: self-signed certificate`.
- Wrong region pooler → `Tenant or user not found` (ours is us-east-2).
- `%` in the DSN → alembic `configparser` interpolation error.
