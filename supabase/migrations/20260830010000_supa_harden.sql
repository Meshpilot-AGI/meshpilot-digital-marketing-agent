-- SUPA-HARDEN: close the two Supabase security-advisor WARNs surfaced in the
-- post-open-source review. RLS is already deny-all everywhere (safe); these are
-- defence-in-depth hardening, not a data-exposure fix.
--
-- Portability: `rls_auto_enable()` + its `ensure_rls` event trigger exist on the
-- live Supabase DB but are NOT defined in these migrations (created out-of-band on
-- the platform), so the from-scratch CI DB won't have the function. Every statement
-- is guarded to be a clean no-op when its target is absent, and idempotent so the
-- CI double-apply passes. The CI job sets search_path=public,extensions (see
-- .github/workflows/ci.yml) so the pgvector relocation below stays idempotent-safe.

-- 1) Stop `rls_auto_enable()` from being callable as an anon/authenticated RPC
--    (/rest/v1/rpc/rls_auto_enable). It is a SECURITY DEFINER function wired to
--    the `ensure_rls` EVENT TRIGGER, which fires on DDL regardless of EXECUTE
--    grants — so revoking the RPC surface does NOT affect auto-RLS. (Lints 0028/0029.)
do $$
begin
  if exists (
    select 1 from pg_proc
    where proname = 'rls_auto_enable'
      and pronamespace = 'public'::regnamespace
  ) then
    execute 'revoke execute on function public.rls_auto_enable() from public';
    if exists (select 1 from pg_roles where rolname = 'anon') then
      execute 'revoke execute on function public.rls_auto_enable() from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
      execute 'revoke execute on function public.rls_auto_enable() from authenticated';
    end if;
  end if;
end $$;

-- 2) Move pgvector out of the API-exposed `public` schema into `extensions`
--    (lint 0014). Consumers reach the type via search_path: prod's `postgres`
--    role has `extensions` in its path, and the CI job sets the same — so the
--    unqualified `halfvec` / `halfvec_cosine_ops` references in the agent_memory
--    migration keep resolving. Only agent_memory.embedding halfvec(2048) depends
--    on the type; its HNSW index follows via pg dependency tracking. Guarded so a
--    re-run (already relocated) is a no-op.
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
