-- DRIVE-TO-SOCIAL — one row per Drive file the agent has posted, per brand.
--
-- The idempotency record for a brand whose content is NOT generated: the videos already exist in a
-- Drive folder and the agent's only job is to post each one exactly once, oldest first. The file id
-- is the identity; a file that is renamed, re-uploaded, or moved is a new file and is posted again,
-- which is the honest reading — the agent cannot know it is the same video.
--
-- Outcome per platform is recorded separately, because IG and TikTok fail independently: a TikTok
-- outage must not cause the IG post to be repeated tomorrow, and vice versa.
create table if not exists drive_post (
  brand_id     text not null,
  file_id      text not null,
  file_name    text not null,
  media_url    text,                        -- the public copy the platforms ingested from
  caption      text,
  ig_media_id  text,                        -- null = not posted to IG (or failed)
  ig_error     text,
  tiktok_post_id text,                      -- Buffer post id; null = not posted (or failed)
  tiktok_error text,
  posted_at    timestamptz not null default now(),
  primary key (brand_id, file_id)
);

alter table drive_post enable row level security;

comment on table drive_post is
  'Drive files the agent has posted, per brand. file_id is identity; per-platform outcomes are '
  'independent so one platform failing never repeats the other.';
