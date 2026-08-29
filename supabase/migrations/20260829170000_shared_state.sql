-- Cross-worker shared state (#98). FastAPI Cloud runs multiple workers, so in-process dicts/sets
-- don't dedup or throttle across the fleet. These two small tables move that state into Postgres.

-- Webhook idempotency: a redelivered event lands on any worker and is deduped fleet-wide.
create table if not exists webhook_dedup (
  provider    text not null,
  event_id    text not null,
  created_at  timestamptz not null default now(),
  primary key (provider, event_id)
);
create index if not exists webhook_dedup_created_idx on webhook_dedup (created_at);

-- Fixed-window rate counters (opt-in shared limiter). One row per (key, window bucket).
create table if not exists rate_counters (
  key           text not null,
  window_start  bigint not null,        -- floor(epoch_seconds / window_seconds)
  count         integer not null default 0,
  primary key (key, window_start)
);
create index if not exists rate_counters_window_idx on rate_counters (window_start);

alter table webhook_dedup enable row level security;   -- service-role only
alter table rate_counters enable row level security;
