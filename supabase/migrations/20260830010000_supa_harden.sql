-- SUPA-HARDEN: close the two Supabase security-advisor WARNs surfaced in the
-- post-open-source review. RLS is already deny-all everywhere (safe); these are
-- defence-in-depth hardening, not a data-exposure fix.

-- 1) Stop the `rls_auto_enable()` maintenance function from being callable as an
--    anon/authenticated RPC (/rest/v1/rpc/rls_auto_enable). It is a
--    SECURITY DEFINER function wired to the `ensure_rls` EVENT TRIGGER, which
--    fires on DDL regardless of EXECUTE grants — so revoking RPC access does NOT
--    affect the auto-RLS behaviour, it only removes the public attack surface.
--    (Advisor lints 0028 / 0029.) Idempotent: revoking an absent grant is a no-op.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

-- 2) Move the pgvector extension out of the API-exposed `public` schema into the
--    dedicated `extensions` schema (advisor lint 0014). Safe here:
--      - the `extensions` schema already exists (Supabase default);
--      - the app connects as `postgres`, whose search_path is
--        `"$user", public, extensions`, so unqualified `halfvec` / `<=>` still
--        resolve after the move;
--      - only one column depends on the type (agent_memory.embedding halfvec(2048));
--        its column + HNSW index follow the extension via pg dependency tracking.
--    Guarded so a re-run (extension already relocated) is a no-op.
create schema if not exists extensions;
do $$
begin
  if exists (
    select 1 from pg_extension e
    join pg_namespace n on n.oid = e.extnamespace
    where e.extname = 'vector' and n.nspname = 'public'
  ) then
    execute 'alter extension vector set schema extensions';
  end if;
end $$;
