-- PLATFORM KNOWLEDGE BASE — who is on each platform and what reads well there.
--
-- Until now one caption was written per MEDIUM and reused across every platform of that medium:
-- the identical text went to X, LinkedIn and Facebook. Those are different audiences with different
-- norms, lengths and registers, and a caption tuned for none of them is tuned for all of them
-- badly. This is the per-platform context the caption writer was missing.
--
-- Per-brand rather than global: the platform's audience is universal, but how a given brand should
-- sound to that audience is not, and a second tenant must be able to differ without a deploy.
create table if not exists platform_profile (
  brand_id     text not null,
  platform     text not null,
  audience     text not null,          -- who is actually there, in this brand's terms
  register     text not null,          -- how to sound: length, formality, structure
  max_chars    int,                    -- hard platform limit, when one exists
  hashtags     text,                   -- the norm here, including "none"
  avoid        text,                   -- what specifically does not work on this platform
  updated_at   timestamptz not null default now(),
  primary key (brand_id, platform)
);

alter table platform_profile enable row level security;

comment on table platform_profile is
  'Per-platform audience + register the caption writer is grounded in. One caption per platform.';

-- Verified social handles for tagging. Deliberately separate from the logo asset: a mark and a
-- handle are different facts with different provenance, and a WRONG handle tags a real stranger's
-- account in public — a worse failure than simply not tagging. Empty until verified; the tagging
-- code treats absence as "do not tag" and never guesses one.
alter table brand_asset add column if not exists handles jsonb not null default '{}'::jsonb;

comment on column brand_asset.handles is
  'Verified per-platform handles, e.g. {"x": "@Example"}. Never inferred — absence means do not tag.';
