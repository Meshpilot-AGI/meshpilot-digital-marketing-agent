-- SEO-3 — the evidence that earns autonomy.
--
-- The amended AI-SEO program grants the agent the right to merge its own posts only after a
-- measured track record: five consecutive posts passing every gate with ZERO human edits to the
-- body. That promise is worthless unless "zero human edits" is a number someone can check, so each
-- authored post is recorded here and settled after its PR closes.
--
-- Deliberately records the CLAIM and the OUTCOME separately: what the agent proposed, and what
-- actually happened to it. A stage is then derived from history rather than configured, so nobody
-- can grant autonomy by flipping a flag — the streak has to exist.
create table if not exists seo_publication (
  id              uuid primary key default gen_random_uuid(),
  brand_id        text not null,
  slug            text not null,
  title           text,

  -- what the agent did
  stage_at_author text not null,               -- S0 | S1 | S2 — the stage it was operating under
  gates           jsonb not null default '{}'::jsonb,
  pr_number       int,
  pr_url          text,
  branch          text,
  authored_at     timestamptz not null default now(),

  -- what happened to it. NULL = not settled yet; settling is a separate, later act.
  merged_at       timestamptz,
  closed_unmerged boolean,
  -- Commits on the branch that were not ours. 0 means the post shipped exactly as proposed, which
  -- is the evidence that earns promotion. NULL means we have not looked yet.
  human_edits     int,
  notes           text,

  unique (brand_id, slug)
);

alter table seo_publication enable row level security;

-- The streak query: newest-first over settled rows for one brand.
create index if not exists seo_publication_brand_idx
  on seo_publication (brand_id, authored_at desc);

comment on table seo_publication is
  'Per-post record of what the agent proposed and what happened to it. The stage is derived from '
  'this history, never configured.';
comment on column seo_publication.human_edits is
  'Commits on the PR branch that were not the agent''s. 0 = shipped exactly as proposed. '
  'NULL = not yet settled.';
