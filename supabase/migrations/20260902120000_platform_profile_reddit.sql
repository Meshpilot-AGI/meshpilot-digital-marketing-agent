-- Reddit's register, as a generic '_default' row (TARGET-3).
--
-- The other platforms were seeded when this table was created; Reddit was absent because the agent
-- could not see Reddit at all. Sensing (TARGET-1) and surface scoring (TARGET-2) now point there, so
-- the caption writer needs to know how the room actually reads.
--
-- Reddit differs from every other platform here in one decisive way: **the audience is actively
-- hostile to marketing**, and unusually good at spotting it. Copy that would pass on LinkedIn —
-- polished, benefit-led, lightly promotional — is precisely what gets downvoted, removed, and
-- remembered. So this row is written mostly as constraints, and the `avoid` field carries more
-- weight here than anywhere else.
--
-- Two constraints are drawn from real rule text captured 2026-09-02, not from intuition:
--   * r/Forex: "Do not self promote here. Doing so risks your brand being blacklisted."
--   * r/Daytrading: "No ChatGPT or AI-Generated Content — Posts or comments created using AI tools
--     like ChatGPT, Claude, or similar language models."
-- The second is why `avoid` names AI-tell phrasing explicitly: on Reddit, *sounding* generated is
-- itself a rule violation in some rooms, independent of what is being said.
--
-- '_default' rather than a tenant's brand_id — this repo is open-core, so only public knowledge
-- about the platform itself is committed here. A brand overrides any field with its own row.
insert into platform_profile (brand_id, platform, audience, register, max_chars, hashtags, avoid)
values
  ('_default', 'reddit',
   'People looking for a specific answer from someone who has actually done the thing. Peer-to-peer, '
   'not brand-to-consumer: they are asking each other, and a brand is tolerated only while it is '
   'useful. Highly literate about marketing and quick to name it.',

   'Write as one practitioner replying to another. Lead with the direct answer, then the reasoning, '
   'then the caveat. First person and specific — what happened, what the number was, what broke. '
   'Plain sentences, no build-up, no summary at the end. Answer the question that was asked rather '
   'than the one you would rather answer; leaving out the pitch entirely is usually the strongest '
   'move available.',

   10000,   -- Reddit''s comment limit; posts allow more, but a long comment is rarely read
   'None. Reddit has no hashtag convention and using one marks the author as an outsider.',

   'Marketing register of any kind: benefits language, taglines, calls to action, "we help X do Y". '
   'Naming or linking your own product unless someone explicitly asked what you use. Opening with '
   '"Great question!" or restating the question back. Emoji, bold-heavy formatting, and listicles '
   'where a paragraph would do. AI-tell phrasing — "delve", "in today''s landscape", "it is '
   'important to note", tidy three-part structures, over-hedging — which reads as generated and is '
   'itself against the rules in some subreddits. Posting the same text to more than one subreddit.')
on conflict (brand_id, platform) do update set
  audience = excluded.audience, register = excluded.register, max_chars = excluded.max_chars,
  hashtags = excluded.hashtags, avoid = excluded.avoid, updated_at = now();
