-- Vendor balance snapshots for COST-METER INC-2 reconciliation.
-- Credit vendors (MUapi, HeyGen, Higgsfield) bill at the account level with no per-tenant tagging,
-- so we true up our self-metered estimate against the vendor's real spend via BALANCE DELTA: the
-- drop in a vendor's queryable balance between two snapshots is the true spend for that window,
-- which we compare to the sum of our usage_events. A large drift flags a stale price book.

create table if not exists balance_snapshots (
  id             uuid primary key default gen_random_uuid(),
  vendor         text not null,               -- 'muapi' | 'heygen' | 'higgsfield'
  balance        numeric(16,4),               -- native units (credits), null if unavailable
  balance_unit   text not null default 'credits',
  raw            jsonb not null default '{}',  -- the vendor's raw balance response
  created_at     timestamptz not null default now()
);

create index if not exists balance_snapshots_vendor_created_idx
  on balance_snapshots (vendor, created_at desc);

alter table balance_snapshots enable row level security;   -- service-role only
