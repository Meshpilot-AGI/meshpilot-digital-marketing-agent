-- Finding 9 (PR #196 review): scope containment (#195) is only checked at SCHEDULE time. A
-- `pipelineTurn` job stores just the pipeline NAME, and `_run_pipeline_turn` deliberately
-- RE-RESOLVES the pipeline from the registry at FIRE time so kill-switches are read live — but a
-- pipeline's scope is not static (e.g. `content` resolves to `content_draft` while
-- `agent_content_media_enabled` is off, and to `content`, which grants media tools, once it's on).
-- A run in a narrow scope could pass the create-time check, then fire later with more power than
-- its creator ever had, the moment an operator flips a switch.
--
-- Fix: persist the CREATING run's scope on the job, so fire-time dispatch can re-check containment
-- against it (in addition to the existing create-time check, kept for fail-fast UX).
alter table scheduled_jobs add column if not exists created_scope text;

comment on column scheduled_jobs.created_scope is
  'Scope of the run that created this job (#196 finding 9). Re-checked at fire time against the '
  'freshly-resolved pipeline/capability scope so a job cannot out-live an operator flipping a '
  'kill-switch into more power than its creator held. NULL on jobs created before this column '
  'existed — treated as the safe default scope (fail closed), not as unlimited trust.';
