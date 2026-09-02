-- TARGET-3 — a second, independent permission dimension: does this room allow AI-GENERATED content?
--
-- Found by reading real subreddit rules before building against assumptions. r/Daytrading:
--
--   "No ChatGPT or AI-Generated Content — Posts or comments created using AI tools like ChatGPT,
--    Claude, or similar language models"
--
-- That is a prohibition on what this agent produces, entirely independent of self-promotion. A room
-- can welcome brand participation and still ban AI-written text; posting there would breach its
-- rules even with a perfectly humble, link-free, on-topic comment.
--
-- NULL means UNKNOWN, and unknown is never permission — same contract as self_promo_allowed.
alter table surface add column if not exists ai_content_allowed boolean;

comment on column surface.ai_content_allowed is
  'NULL = unknown. FALSE where the room bans AI-generated posts/comments (e.g. r/Daytrading). '
  'Independent of self_promo_allowed: a room may welcome brands but ban AI-written text.';
