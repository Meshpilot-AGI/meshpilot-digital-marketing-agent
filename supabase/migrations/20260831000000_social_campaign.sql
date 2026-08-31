-- SOCIAL-CAMPAIGN: coordinated multi-platform posts (dedup + per-platform idempotency).
create table if not exists social_campaign (
  id          uuid primary key default gen_random_uuid(),
  brand_id    text not null,
  dedup_key   text not null,
  idea        jsonb not null,
  image_url   text,
  video_url   text,
  status      text not null default 'draft',   -- draft|posted|partial|held|failed|skipped
  cost_usd    numeric,
  created_at  timestamptz not null default now()
);
create index if not exists social_campaign_brand_created on social_campaign (brand_id, created_at desc);
create index if not exists social_campaign_brand_dedup on social_campaign (brand_id, dedup_key);
alter table social_campaign enable row level security;

create table if not exists social_post (
  id               uuid primary key default gen_random_uuid(),
  campaign_id      uuid not null references social_campaign(id) on delete cascade,
  platform         text not null,
  media_kind       text not null,               -- image|video
  caption          text,
  verdict          text,                         -- pass|concerns|escalate
  status           text not null,                -- posted|held|failed|skipped
  platform_post_id text,
  post_url         text,
  error            text,
  created_at       timestamptz not null default now(),
  unique (campaign_id, platform)                 -- idempotency
);
alter table social_post enable row level security;
