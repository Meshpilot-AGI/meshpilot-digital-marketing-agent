-- DELIBERATION Phase 1/2 — persist the reckoning + conscience passes on the run record so they are
-- pollable via GET /internal/agent/run/{id}, not only folded into the loop's memory episode.
-- Additive + idempotent; existing rows default to an empty object.
alter table agent_runs add column if not exists deliberation jsonb not null default '{}';
