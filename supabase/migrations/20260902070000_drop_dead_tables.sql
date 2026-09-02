-- DB-OPT Tier 1 — drop the tables that are dead by every measure.
--
-- The survey (2026-09-02, control-plane/ACTIVE_LANE_BOARD.md) checked all 32 public tables three
-- ways: raw-SQL reference, ORM `__tablename__`, and whether the ORM class is used anywhere outside
-- db/models.py. These six had none of the three and hold no rows.
--
-- Verified safe before writing this:
--   * no FOREIGN KEY from a surviving table points at any of them,
--   * there are no views in `public`,
--   * `create_all_tables()` — which would have recreated them from SQLModel metadata at boot — is
--     never called anywhere in the codebase.
--
-- `orm_response` goes first: it carries the only FK among the six, pointing at `mention_event`.

drop table if exists public.orm_response;
drop table if exists public.mention_event;
drop table if exists public.comment_reply;
drop table if exists public.strategic_reply;

-- Orphaned by PR #216, which removed `read_brand_doc` and the three brand-document endpoints.
drop table if exists public.brand_document;

-- Alembic is entirely gone — 0 files under alembic/versions/, and CI never references it. This repo
-- applies Supabase-native SQL migrations through the GitHub integration, so the version table left
-- behind by the old tooling tracks nothing.
drop table if exists public.alembic_version;
