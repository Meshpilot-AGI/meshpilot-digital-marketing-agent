-- OAuth token refresh could never persist: the encryption migration (#91) added the `*_enc`
-- columns and `agent/mcp/oauth.py::_UPDATE` moves a row off plaintext by writing the ciphertext
-- and NULLing the legacy columns -- but `access_token` was left NOT NULL. Every refresh therefore
-- raised NotNullViolationError and rolled back, leaving the EXPIRED access token in place, so a
-- token could never recover once it lapsed. Both configured MCP servers silently fell to 0 tools
-- this way (heygen expired 2026-08-29, higgsfield 2026-08-31).
--
-- The ciphertext column is the store of record now; plaintext is a legacy fallback only.
alter table public.oauth_tokens alter column access_token drop not null;

-- Preserve the original intent of the NOT NULL -- a row must still carry an access token in one
-- form or the other -- without blocking the plaintext -> ciphertext migration the refresh performs.
alter table public.oauth_tokens
  drop constraint if exists oauth_tokens_access_token_present;
alter table public.oauth_tokens
  add constraint oauth_tokens_access_token_present
  check (access_token is not null or access_token_enc is not null);
