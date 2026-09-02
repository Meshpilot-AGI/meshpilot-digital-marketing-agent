-- DB-OPT Tier 2 — drop the legacy LangGraph pipeline's tables, now that the pipeline is gone.
--
-- Removed with it: agent/graph.py, agent/nodes/ (12 files), scheduler/ (2 files), the
-- `drive_scout` cron capability, the /jobs/{scout,assemble,drive_scout} endpoints, and the
-- file-based buffer.publish() path. All eight tables held zero rows.
--
-- Dropped leaf-first, following the FKs:
--   signal <- content_script <- {video_job, video_asset, scheduled_post}
--   content_script <- video_asset <- scheduled_post <- published_post <- metrics_snapshot
-- No FOREIGN KEY from a surviving table points at any of them, and there are no views in `public`.
--
-- NOT dropped: `platform_auth`. It holds a LIVE active YouTube OAuth credential for
-- glitch_executor (created 2026-08-29), and the /oauth/youtube/{start,callback} endpoints that
-- issue it are still mounted. Retiring YouTube is a separate product decision.

drop table if exists public.metrics_snapshot;
drop table if exists public.published_post;
drop table if exists public.scheduled_post;
drop table if exists public.video_asset;
drop table if exists public.video_job;
drop table if exists public.content_script;
drop table if exists public.scout_checkpoint;
drop table if exists public.signal;
