-- Self-cron (AGENT-CRON): the agent schedules its own future work.
-- `scheduled_jobs` holds job definitions; the per-worker scheduler tick claims due jobs with
-- FOR UPDATE SKIP LOCKED (exactly-once across workers), advances next_run_at, and dispatches the
-- payload. `scheduled_runs` is the run-history / background-task ledger. NOT the social-post
-- scheduler — this is the agent operating on itself on a clock.

create table if not exists scheduled_jobs (
  id               uuid primary key default gen_random_uuid(),
  brand_id         text not null,
  name             text not null,
  owner            text not null default 'operator',   -- 'operator' | 'agent:<brand>' (self-scoping)
  enabled          boolean not null default true,
  schedule_kind    text not null,                       -- 'at' | 'every' | 'cron'
  schedule         jsonb not null default '{}',         -- {at?, every_ms?, cron_expr?, tz?}
  payload_kind     text not null,                       -- 'agentTurn' | 'capability'
  payload          jsonb not null default '{}',         -- agentTurn {goal,max_steps} | capability {name,args}
  next_run_at      timestamptz,                         -- claim key; null once a one-shot is spent
  last_run_at      timestamptz,
  pacing           jsonb not null default '{}',         -- {min_ms?, max_ms?} for next_check self-pacing
  delete_after_run boolean not null default false,      -- one-shot 'at' cleanup
  fail_count       int not null default 0,              -- consecutive failures → auto-disable
  disabled_reason  text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- Unique job name per (brand, owner) so create is idempotent-ish and the agent can't shadow itself.
create unique index if not exists scheduled_jobs_brand_owner_name_idx
  on scheduled_jobs (brand_id, owner, name);
-- The sweep: due, enabled jobs ordered by next_run_at.
create index if not exists scheduled_jobs_due_idx
  on scheduled_jobs (enabled, next_run_at);
create index if not exists scheduled_jobs_brand_owner_idx
  on scheduled_jobs (brand_id, owner);

create table if not exists scheduled_runs (
  id           uuid primary key default gen_random_uuid(),
  job_id       uuid not null,
  brand_id     text not null,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  status       text not null default 'running',         -- 'running' | 'done' | 'error' | 'skipped'
  result       jsonb,                                    -- agentTurn {run_id} | capability summary
  error        text
);

create index if not exists scheduled_runs_job_started_idx
  on scheduled_runs (job_id, started_at desc);

alter table scheduled_jobs enable row level security;    -- service-role only
alter table scheduled_runs enable row level security;
