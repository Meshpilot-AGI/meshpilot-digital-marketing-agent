-- SUPA-HARDEN: close the Supabase security-advisor WARN that's worth fixing
-- cleanly. RLS is already deny-all everywhere (safe); this is defence-in-depth.
--
-- Portability note: `rls_auto_enable()` + its `ensure_rls` event trigger exist on
-- the live Supabase DB but are NOT defined in these migrations (created out-of-band
-- on the Supabase platform), so the from-scratch CI DB won't have the function.
-- Every statement is guarded to be a clean no-op when its target is absent, and
-- idempotent so the CI double-apply passes.
--
-- Scope: revoke only. The advisor also flags `vector` living in the `public`
-- schema (lint 0014), but moving it (`alter extension vector set schema extensions`)
-- makes every UNQUALIFIED `halfvec`/`vector` opclass reference depend on
-- `extensions` being in the session search_path — which the CI's `psql` sessions
-- (search_path = public) do NOT have, so the earlier agent_memory HNSW-index
-- migration fails its idempotency re-apply. Relocating pgvector correctly needs a
-- coordinated change (create it in `extensions` from init_schema + put `extensions`
-- on the relevant search_paths, or schema-qualify every opclass). Deferred to its
-- own lane; "extension in public" is a benign, Supabase-default state. See the
-- SUPA-HARDEN supervisor entry.

-- Stop `rls_auto_enable()` from being callable as an anon/authenticated RPC
-- (/rest/v1/rpc/rls_auto_enable). It is a SECURITY DEFINER function wired to the
-- `ensure_rls` EVENT TRIGGER, which fires on DDL regardless of EXECUTE grants — so
-- revoking the RPC surface does NOT affect auto-RLS. (Advisor lints 0028 / 0029.)
-- Revoking from PUBLIC is what actually removes anon/authenticated access (default
-- function grants go to PUBLIC); the per-role revokes are belt-and-suspenders,
-- guarded on the roles existing.
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
