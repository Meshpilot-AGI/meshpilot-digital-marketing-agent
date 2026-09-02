-- TARGET-1 — what the agent has SEEN. The first sensing memory it has ever had.
--
-- Discovery has been ephemeral: `discover_trending` pulls, the model reads the JSON inside one run,
-- and the observation dies with the run. Nothing accumulates, so nothing can be ranked over time and
-- the same thread can be "discovered" every night without anyone noticing.
--
-- A signal_item is one observed thing worth possibly reacting to: a Reddit thread, a search result,
-- a post. It is raw perception — NOT a decision to act. Scoring and surface selection read from
-- here; they are deliberately separate tables so that re-scoring never means re-fetching.
--
-- Per-brand, like everything else: two brands watching the same room care about different threads,
-- and a second tenant must never see the first's observations.
create table if not exists signal_item (
  id            uuid primary key default gen_random_uuid(),
  brand_id      text not null,
  source        text not null,               -- 'reddit' | 'serp' | 'x' ... the sensing channel
  kind          text not null,               -- 'post' | 'community' | 'result'
  external_id   text not null,               -- the platform's own id, for dedup across runs
  surface       text,                        -- where it was seen (e.g. subreddit name)
  title         text,
  excerpt       text,                        -- trimmed body: enough to judge relevance, not the lot
  author        text,
  url           text,
  score         int,                         -- upvotes / rank / whatever the source calls traction
  comment_count int,
  query         text,                        -- the query that surfaced it — why we are looking at it
  observed_at   timestamptz not null default now(),
  raw           jsonb not null default '{}'::jsonb,
  -- One row per thing per brand. Re-observing updates traction rather than duplicating the item,
  -- which is what makes "has this been seen before" answerable at all.
  unique (brand_id, source, external_id)
);

alter table signal_item enable row level security;

-- The two reads this table exists to serve: "what is new for this brand" and "what have we seen in
-- this room". Both are time-ordered, hence the descending index.
create index if not exists signal_item_brand_seen_idx on signal_item (brand_id, observed_at desc);
create index if not exists signal_item_surface_idx    on signal_item (brand_id, surface, observed_at desc);

comment on table signal_item is
  'Raw observations from discovery (Reddit threads, SERP results). Perception, not decisions.';
