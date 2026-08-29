-- Encrypt MCP-vendor OAuth tokens at rest (#91). Add ciphertext columns; the app (agent/mcp/oauth.py)
-- writes only the *_enc columns (Fernet, via glitch_signal.crypto) and nulls the legacy plaintext on
-- every write, reading plaintext only as a fallback for un-migrated rows. Old plaintext columns are
-- kept for a safe rollout and dropped in a later migration once all rows have refreshed to *_enc.

alter table oauth_tokens add column if not exists access_token_enc  text;
alter table oauth_tokens add column if not exists refresh_token_enc text;
