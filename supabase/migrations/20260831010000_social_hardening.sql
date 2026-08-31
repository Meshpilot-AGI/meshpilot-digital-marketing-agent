-- SOCIAL-CAMPAIGN hardening (idempotent; applies to the already-created tables from
-- 20260831000000 as well as fresh CI/shadow DBs — we do NOT edit the earlier applied file).
--
-- (1) DB-enforced dedup: a unique index on (brand_id, dedup_key) so concurrent runs cannot both
--     reserve/create the same idea. Enables ON CONFLICT (brand_id, dedup_key) in reserve_campaign.
create unique index if not exists social_campaign_brand_dedup_uk
  on social_campaign (brand_id, dedup_key);

-- (2) Campaign failure reason, so a paid run that fails after reservation records WHY.
alter table social_campaign add column if not exists failure_reason text;

-- social_post.status now also carries the durable outbox states:
--   pending  = row reserved before the external publish, OR a Buffer submission that has not yet
--              reached a terminal "sent" state (Buffer returns "sending", which is NOT terminal);
--   posted   = a synchronous terminal success (Meta), or a reconciled Buffer post;
--   held | failed | skipped as before. (text column, no CHECK — no schema change needed.)
