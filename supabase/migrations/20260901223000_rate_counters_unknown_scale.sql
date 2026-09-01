-- Fix #196: 20260901000000 (fix #193) added `rate_counters.window_seconds` as `not null default 60`
-- and Postgres backfilled EVERY pre-existing row with that default — including 86400s daily
-- email-cap buckets, which got mislabeled as 60s-scale. The #193 scale-aware cleanup
-- (`window_start * window_seconds < now - 3*window_seconds`) then read those buckets' wall-clock
-- expiry as decades in the past and deleted them on the very next sweep, resetting active daily
-- caps during rollout.
--
-- We cannot tell, after the fact, which backfilled rows were genuinely 60s counters and which were
-- mislabeled 86400s+ (or other) buckets — so rather than guess, mark every row backfilled by that
-- migration as UNKNOWN scale (NULL) instead. shared_state.cleanup() (this same fix) now skips
-- unknown-scale rows entirely rather than pruning them, and shared_state.SharedWindowLimiter's
-- upsert (also fixed alongside this migration) repairs a row's window_seconds to the caller's real
-- value on every conflicting write — so each row self-heals to its correct scale the next time its
-- key is touched, which for an active counter is within one window.
alter table rate_counters alter column window_seconds drop not null;
alter table rate_counters alter column window_seconds drop default;

-- Every row in the table right now was written before this fix landed, so its stored scale is not
-- trustworthy — null it out rather than leave rows silently mislabeled as "60s, verified".
update rate_counters set window_seconds = null;
