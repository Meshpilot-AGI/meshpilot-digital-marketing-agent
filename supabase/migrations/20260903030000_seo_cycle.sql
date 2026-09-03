-- SEO-6 — every cycle leaves a row, so a failure is a query rather than a log grep.
--
-- The scheduled cycle's only output was a log file on one machine that nothing reads. A silent
-- failure at 06:40 was indistinguishable from a quiet day: both produce no PR. That is the same
-- "looks healthy, does nothing" shape the cloud schedule was rejected for, reintroduced on the Mac.
--
-- Records EVERY outcome, refusals included — a refusal is normal (disabled, no repo, nothing to say)
-- and the useful signal is the gap between rows, not the presence of a bad one.
create table if not exists seo_cycle (
  id          uuid primary key default gen_random_uuid(),
  brand_id    text not null,
  ran_at      timestamptz not null default now(),
  ok          boolean not null,            -- false = the cycle itself broke, not a refusal
  outcome     text not null,               -- published | refused | author_failed | error
  detail      text,
  slug        text,
  pr_url      text,
  settled     jsonb not null default '{}'::jsonb
);

alter table seo_cycle enable row level security;

create index if not exists seo_cycle_brand_idx on seo_cycle (brand_id, ran_at desc);

comment on table seo_cycle is
  'One row per scheduled SEO cycle, refusals included. Silence between rows is the alarm.';
