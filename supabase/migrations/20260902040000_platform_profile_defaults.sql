-- Seed generic per-platform defaults so `platform_profile` is never empty on a fresh install.
--
-- The prior migration created the table but inserted no rows, so every profile lookup returned {}
-- on deployment: captions were generated with no audience/register/limit context at all, silently
-- falling back to the old generic per-medium behaviour despite this feature having shipped.
--
-- These rows use the reserved brand_id '_default' rather than a real tenant's brand_id — this repo
-- is open-core (see brand_positioning.sql), so a real brand's specific voice/register can never be
-- committed here. What CAN be committed is public knowledge about each platform itself (who is
-- generally there, the platform's own stated limits, common norms) — the same kind of fact any
-- brand operating there would already know. `platforms_kb.profile()` prefers a brand-specific row
-- when one exists and falls back to '_default' only when it does not, so a tenant can always
-- override any or all of these without a deploy.
insert into platform_profile (brand_id, platform, audience, register, max_chars, hashtags, avoid)
values
  ('_default', 'x',
   'Fast-scrolling, high-signal audience; short attention span, rewards a sharp claim over a long '
   'explanation.',
   'Terse. One idea per post, stated directly. Save elaboration for a reply or thread.',
   280, 'Rarely — at most one, never a hashtag string.',
   'Long paragraphs, corporate tone, more than one hashtag.'),

  ('_default', 'linkedin',
   'Professional, career- and industry-focused; reads for relevance to their own work.',
   'Slightly longer-form and still concrete; a personal or narrative hook works well here.',
   3000, 'Three to five, placed at the end of the post.',
   'Overt sales language, emoji overload, engagement-bait phrasing ("agree?").'),

  ('_default', 'facebook',
   'Broad, general audience skewing older; casual browsing, not a professional context.',
   'Conversational and plain-spoken, closer to how the brand would actually talk to someone.',
   null, 'Uncommon; plain text reads better here than tags.',
   'Jargon, assuming platform-native slang the audience does not use.'),

  ('_default', 'instagram',
   'Visual-first, younger-skewing audience; scans the caption briefly under the image or reel.',
   'Short caption that supports the image rather than competing with it; can be a little more '
   'expressive than X.',
   2200, 'A handful of directly relevant tags, not a block of unrelated ones.',
   'Walls of text — the image should carry the idea, not the caption.'),

  ('_default', 'tiktok',
   'Very online, entertainment-first audience with low patience for anything that reads like an ad.',
   'Casual and first-person, written the way the video''s captions actually sound.',
   2200, 'A few trending or directly relevant tags.',
   'Corporate voice, a hard sell, anything that reads like a press release.')
on conflict (brand_id, platform) do nothing;
