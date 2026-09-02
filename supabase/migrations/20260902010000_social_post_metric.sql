-- OUTCOME INGESTION — what actually happened to a published post.
--
-- Until now the learning loop had no sensor. `curator.py` distils `kind='episode'` memories, which
-- are the agent's own record of what it DID; nothing anywhere read back what any post ACHIEVED. So
-- the agent could write itself a durable lesson ("comparison posts land well") from a post that
-- flopped, because its only evidence was its own narration.
--
-- Stored as a TIME SERIES, one row per collection, not a single mutable snapshot: engagement
-- accrues over days, so a lone reading says nothing about trajectory, and overwriting would destroy
-- the very comparison the loop needs (a post at 1h vs the same post at 7d).
create table if not exists social_post_metric (
  id            uuid primary key default gen_random_uuid(),
  post_id       uuid not null references social_post(id) on delete cascade,
  platform      text not null,
  collected_at  timestamptz not null default now(),
  age_bucket    text not null,          -- 1h | 24h | 7d — which scheduled reading this is
  impressions   bigint,
  reach         bigint,
  likes         bigint,
  comments      bigint,
  shares        bigint,
  saves         bigint,
  clicks        bigint,
  video_views   bigint,
  raw           jsonb not null default '{}'::jsonb,
  unique (post_id, age_bucket)          -- one reading per bucket; re-collection is idempotent
);

create index if not exists social_post_metric_post on social_post_metric (post_id, collected_at desc);
alter table social_post_metric enable row level security;

comment on table social_post_metric is
  'Time series of per-post performance. The learning loop''s only source of measured outcome.';
