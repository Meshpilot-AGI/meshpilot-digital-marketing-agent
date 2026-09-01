-- OPERATIONAL REPAIR — run MANUALLY, before migrations, on a database that has historical
-- duplicate (brand_id, dedup_key) campaigns. Not a migration; deliberately not in the migration
-- sequence. Safe to run repeatedly.
--
-- Why this is not a migration (PR #196, finding 11):
--   Migration runners apply files in timestamp order, and 20260831010000_social_hardening.sql
--   creates the unique index WITHOUT first removing duplicates. On a database that has them, that
--   file fails — and processing stops there, so any later cleanup migration is never reached. A fix
--   can therefore only arrive OUT of band, ahead of the runner. Editing the applied file instead
--   would put the repo out of sync with what production actually ran.
--
-- Why consolidation and not deletion (PR #196, finding 1):
--   `social_post.campaign_id` is ON DELETE CASCADE. Deleting a duplicate campaign therefore erases
--   its published-post records — real publication history, with real provider ids — and drops the
--   spend attributed to it. Before uniqueness existed, each duplicate could independently own posts
--   and cost, so the rows being discarded are exactly the ones worth keeping.
--
-- Strategy: keep the OLDEST campaign per (brand_id, dedup_key); move the others' posts onto it,
-- sum their spend onto it, and only then delete the now-empty duplicates.

begin;

create temporary table _dedup_map on commit drop as
select c.id as dup_id, k.keep_id
from social_campaign c
join (
  select brand_id, dedup_key,
         (array_agg(id order by created_at, id))[1] as keep_id
  from social_campaign
  group by brand_id, dedup_key
  having count(*) > 1
) k on k.brand_id = c.brand_id and k.dedup_key = c.dedup_key
where c.id <> k.keep_id;

-- 1. Carry the duplicates' spend onto the keeper before anything is removed.
update social_campaign keep
set cost_usd = coalesce(keep.cost_usd, 0) + agg.extra
from (select m.keep_id, sum(coalesce(d.cost_usd, 0)) as extra
      from _dedup_map m join social_campaign d on d.id = m.dup_id
      group by m.keep_id) agg
where keep.id = agg.keep_id;

-- 2. Reparent posts onto the keeper, but ONLY where the keeper has no row for that platform —
--    social_post is unique on (campaign_id, platform), so a colliding move would fail.
update social_post p
set campaign_id = m.keep_id
from _dedup_map m
where p.campaign_id = m.dup_id
  and not exists (select 1 from social_post q
                  where q.campaign_id = m.keep_id and q.platform = p.platform);

-- 3. Anything still attached to a duplicate collides with a post the keeper already has. Park it
--    rather than let the cascade delete it: a genuine publication record with a provider id is not
--    something to discard silently.
create table if not exists social_post_orphaned (like social_post including all);
insert into social_post_orphaned
select p.* from social_post p join _dedup_map m on p.campaign_id = m.dup_id
on conflict do nothing;

-- 4. Now the duplicates own nothing irreplaceable.
delete from social_campaign c using _dedup_map m where c.id = m.dup_id;

-- 5. Enforce uniqueness so the blocked migration can proceed.
create unique index if not exists social_campaign_brand_dedup_uk
  on social_campaign (brand_id, dedup_key);

select (select count(*) from social_post_orphaned) as parked_posts;

commit;
