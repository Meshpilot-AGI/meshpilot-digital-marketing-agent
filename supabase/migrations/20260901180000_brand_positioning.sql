-- BRAND POSITIONING: the narrative brand context the content pipeline is grounded in.
--
-- Atomic `agent_memory` facts answer "what is true about this brand". They cannot carry VOICE,
-- the never-say list, or the reasoning behind a positioning choice — and that gap is what let the
-- agent invent "prop firm payout" content for a brand that is not a prop firm.
--
-- This lives in the DB, not on disk, on purpose: the repo is open-core, so brand-specific content
-- must never be committed, and gitignored files under brand/prompts/ do not survive a deploy.
create table if not exists brand_positioning (
  brand_id    text primary key,
  content     text not null,
  updated_at  timestamptz not null default now(),
  updated_by  text
);

alter table brand_positioning enable row level security;

comment on table brand_positioning is
  'Per-brand narrative positioning doc read by the ideator, the caption writer and the conscience critic.';
