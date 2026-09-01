-- Machine-checkable guardrails beside the prose positioning doc.
--
-- The doc states the never-say list for the models; this states it for CODE, so a prohibited phrase
-- fails a draft deterministically BEFORE any paid generation, instead of relying on the critic to
-- catch it after the spend.
alter table brand_positioning add column if not exists guardrails jsonb not null default '{}'::jsonb;

comment on column brand_positioning.guardrails is
  'Deterministic guardrails: {prohibited: [phrases], banned_imagery: "..."} checked pre-generation.';
