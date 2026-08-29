-- AGENT-LOOP background runs — shared, cross-worker status store.
-- The run endpoint is backgrounded (returns run_id immediately) and the loop runs under
-- asyncio.create_task. FastAPI Cloud runs multiple workers, so an in-process dict cannot be
-- polled reliably (POST and GET can land on different workers). Persist run state here so any
-- worker can read it. Low volume, ephemeral rows; safe to prune periodically.

create table if not exists agent_runs (
  run_id      text primary key,
  brand_id    text not null,
  goal        text not null,
  status      text not null default 'running' check (status in ('running', 'done', 'error')),
  steps       int,
  final       text,
  transcript  jsonb not null default '[]',
  error       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists agent_runs_brand_created_idx
  on agent_runs (brand_id, created_at desc);

-- Service-role only (the app connects with the service key); no anon/authenticated access.
alter table agent_runs enable row level security;
