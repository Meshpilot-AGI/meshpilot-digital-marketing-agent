-- Pipeline smoke test — negligible, idempotent DDL to confirm the Supabase
-- GitHub integration applies + records migrations on merge to production.
-- COMMENT ON is a no-op-safe metadata change (reversible: set back to NULL).
COMMENT ON TABLE signal IS 'pipeline-ok 2026-08-29T06:00Z (supabase github integration verified)';
