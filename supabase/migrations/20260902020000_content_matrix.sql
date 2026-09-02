-- CONTENT MATRIX — record the CHOICES behind each campaign, and the brand's content strategy.
--
-- Outcome data is only useful if you can say what produced it. `social_post_metric` now measures
-- what happened; nothing recorded what was DECIDED — which asset kind, which pillar, which route.
-- Without that, a lesson like "comparison posts land well" is unfalsifiable: there is no column to
-- group by, and no way to tell a good idea from a lucky one.
--
-- And without deliberate VARIATION there is nothing to compare in the first place. If the agent
-- always reaches for the same shape, every measurement describes that one shape and the loop has no
-- contrast to learn from. Coverage of the matrix is what turns a stream of posts into an experiment.
alter table social_campaign add column if not exists choices jsonb not null default '{}'::jsonb;

create index if not exists social_campaign_choices_kind
  on social_campaign ((choices->>'asset_kind'), (choices->>'pillar'));

comment on column social_campaign.choices is
  'What the agent DECIDED: asset_kind, pillar, route, layout. The group-by for outcome analysis.';

-- Content strategy lives with the brand, beside its voice and guardrails, not in code — a second
-- brand has different pillars and must not need a deploy to say so.
alter table brand_positioning add column if not exists strategy jsonb not null default '{}'::jsonb;

comment on column brand_positioning.strategy is
  'Content strategy: {pillars: [...]} — the dimensions the content matrix varies across.';
