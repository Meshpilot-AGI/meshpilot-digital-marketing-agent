-- TARGET-2 — SURFACES: the rooms a brand could speak in, and how good each one is for it.
--
-- The content matrix decides what FORMAT to make. Nothing decided WHERE to say it, so the agent
-- broadcast to a fixed platform list and never asked whether its audience was there. A surface is
-- a place a conversation happens — a subreddit, an X account or hashtag, a search query, a forum.
--
-- Surfaces are DISCOVERED and SCORED, never hardcoded. The brand declares who it serves; sensing
-- (TARGET-1) finds where they gather. That is simultaneously better targeting and the reason no
-- subreddit name appears anywhere in the code: a second brand runs the same machinery and lands on
-- an entirely different set of rooms.
create table if not exists surface (
  id                 uuid primary key default gen_random_uuid(),
  brand_id           text not null,
  kind               text not null,               -- subreddit | x_account | x_hashtag | query | forum
  handle             text not null,               -- the room's own identifier, e.g. a subreddit name
  display_name       text,

  -- lifecycle. `read_only` is a real destination, not a failure: a room whose rules forbid
  -- self-promotion is still worth LISTENING to, and must never be posted into.
  status             text not null default 'candidate',   -- candidate | active | read_only | blocked

  -- evidence the score is built from, kept as data so re-scoring never means re-fetching
  reach              bigint,                      -- subscribers / followers: the ceiling on reach
  signal_count       int not null default 0,      -- observations seen here (relevance density)
  last_signal_at     timestamptz,

  -- posture, captured BEFORE we ever act here
  rules              jsonb not null default '{}'::jsonb,
  rules_fetched_at   timestamptz,
  self_promo_allowed boolean,                     -- null = unknown, and unknown is not permission

  -- the score, with its inputs kept alongside it so a ranking can always be explained
  fit_score          numeric,
  score_components   jsonb not null default '{}'::jsonb,
  scored_at          timestamptz,
  -- TRUE until enough measured engagement exists here. A provisional score is a prior, not a
  -- finding, and callers are expected to say so rather than present it as evidence.
  provisional        boolean not null default true,

  discovered_at      timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (brand_id, kind, handle)
);

alter table surface enable row level security;

-- The one query this table exists to answer: "where should this brand speak next?"
create index if not exists surface_brand_rank_idx
  on surface (brand_id, status, fit_score desc nulls last);

comment on table surface is
  'Rooms a brand could participate in, discovered by sensing and scored on measured evidence.';
comment on column surface.provisional is
  'Score is a prior, not a finding — no measured engagement here yet.';
comment on column surface.self_promo_allowed is
  'NULL means unknown. Unknown is not permission: posting requires an explicit true.';
