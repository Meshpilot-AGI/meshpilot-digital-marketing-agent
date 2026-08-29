---
name: social-copy
description: Per-platform caption and social-copy craft — house voice rules plus format specs for TikTok, Instagram, YouTube Shorts, X, and LinkedIn.
---

# Social Copy Playbook

Brand-neutral craft for writing organic social captions and posts. Load this
before any node generates caption, hook, or post-body text. It has two parts:
the house voice rules (apply everywhere, every platform) and per-platform
format specs (apply on top, per destination).

## Part 1 — House voice: write like a human, not a model

The single biggest quality signal on a caption is whether it reads like a
person wrote it in one sitting. These rules exist to kill the "AI tell."

- **No em-dashes or en-dashes (— –).** The most common AI tell. Use a period,
  a comma, or restructure the sentence. If a draft has one, rewrite it — don't
  just swap the punctuation mark.
- **No tricolon / triple-parallel structure.** Three short punchy
  clauses or sentences in a row ("Fast. Simple. Free.") is the strongest
  paragraph-level machine signal. Break the pattern — vary the rhythm.
- **Banned words and phrases:** delve, leverage, foster, harness, underscore,
  embark, unleash, elevate, navigate, landscape, realm, tapestry, ecosystem,
  seamless, robust, game-changer, revolutionize, "in today's fast-paced
  world," "rapidly evolving," "not only ... but also," "it's not just X,
  it's Y."
- **Take a position.** No hedging ("it depends," "both have merit"). A
  caption that refuses to commit to a point of view reads as filler.
- **Vary sentence length (burstiness).** Mix a six-word sentence with a
  twenty-word one. Use contractions. A rhetorical question is fine
  occasionally — never as a transition device every few lines.
- **No emoji spam.** One or two emojis, used with intent, beat a caption
  sprinkled with them at every line break.
- **No hashtag walls.** Hashtags earn their place per the platform norms
  below — never pad to "look thorough."
- **Never invent numbers, stats, or claims** the source material didn't give
  you. If you don't have a real number, don't imply one.
- **Never mention being an AI, a bot, or a generated post.**

Enforcement in production is layered: these rules are baked into the
generation prompt, a deterministic sanitizer strips stray em/en dashes before
queueing, and a self-review pass rejects anything that still reads off-voice.
Write as if all three checks are watching.

## Part 2 — Per-platform specs

### TikTok

- **Length:** caption ≤ 2000 characters total. Title field (used for the
  on-platform title, separate from the caption) ≤ 100 characters.
- **Hook:** the first ~80 characters are what shows before the feed's "...
  more" cutoff — the hook has to work standalone in that window. Front-load
  the payoff or the tension, not a setup.
- **Hashtags:** 3–8, space-separated, all lowercase, no punctuation inside
  the tag. Put them at the end of the caption, not woven through the body.
- **Emoji:** at most 2 in the whole caption — no emoji walls.
- **CTA style:** implicit through the hook and pacing more than an explicit
  ask; when you do ask, keep it native ("watch till the end," "part 2 in
  bio") rather than a hard sell.
- **Avoid:** caption as a second script — TikTok captions supplement the
  video, they don't re-narrate it line for line.

### Instagram (Reels and feed)

- **Length:** hard platform limit is 2200 characters. Target a strong first
  line within the first 125 characters (that's the pre-"more" preview
  window), then a 150–220 word body.
- **Hook:** the opening line needs to stand alone in the feed preview — lead
  with the specific and concrete, not a generic greeting.
- **Structure:** short first-person lines with line breaks (not dense
  paragraphs), then a soft save/follow nudge, then a blank line before
  hashtags.
- **Hashtags:** 3–5 niche, relevant tags on one line at the end (hard cap 5
  — more reads as spam and the algorithm doesn't reward volume). Keyword-rich
  caption copy now matters more for discovery than hashtag count; write the
  body as if it needs to be found by search, not just tags.
- **Disclosure:** append any required creator/affiliate disclosure after the
  hashtag line, not buried mid-caption.
- **CTA style:** "save this for later," "follow for more," "link in bio" —
  soft, native asks. Avoid a hard sales CTA in-caption.
- **Avoid:** hashtag walls past 5, generic openers ("Hey guys!"), caption
  that just repeats the on-screen text verbatim.

### YouTube Shorts

- **Length:** title ≤ 100 characters, ideally under 60 so it doesn't clip on
  mobile. Description can be longer but the first 1–2 lines are what shows
  before "more" — put the value proposition and any link there.
- **Hook:** the title and the first on-screen second do the hook's job
  together — the caption/description hook matters less here than on
  Instagram/TikTok, but still front-load the specific claim or question.
- **Hashtags:** 3–5 in the description, one of which can be `#shorts` if
  relevant to discovery; don't over-tag.
- **CTA style:** subscribe/follow asks land better in the description than
  crammed into the title. Keep it to one ask.
- **Avoid:** clickbait titles that don't pay off in the first 3 seconds —
  Shorts completion rate punishes a title/content mismatch harder than any
  other platform.

### X (Twitter)

- **Length:** hard max 280 characters; ideal range 71–100 for a single
  sharp-idea post. Longer needs a thread (4–8 posts), not a wall of text in
  one tweet.
- **Hook:** the entire first tweet often IS the hook — one sharp idea, no
  throat-clearing setup line.
- **Hashtags:** 0–1. More than one reads as noise on this platform.
- **Links:** put the link in the first reply, not the parent post — parent
  posts with a link get suppressed in reach. Keep the parent tweet link-free.
- **CTA style:** implicit — a strong claim or question that invites a reply
  or quote-tweet works better than an explicit "click here."
- **Avoid:** thread padding (stretching one idea across 8 tweets when 2
  would do), engagement-bait phrasing ("WHO ELSE struggles 👇," "drop a 🔥
  if..."), hashtag stuffing.

### LinkedIn

- **Length:** 1,300–1,900 characters for a full post; 400–800 for a quick
  hot take. Hard ceiling around 2,800 if a longer essay format is used
  intentionally.
- **Hook:** one line, then a blank line before the body — the hook has to
  work as a standalone sentence since LinkedIn truncates aggressively before
  "see more."
- **Structure:** 1–3 sentence paragraphs, blank line between each. Dense
  paragraphs get skipped on this platform more than any other.
- **Hashtags:** 0–3, placed at the very end only, never inline.
- **Emoji:** 0–3 total, and never in the hook line — LinkedIn audiences read
  emoji-heavy hooks as unserious.
- **CTA style:** one clear ask, most often "save this" or a direct question
  inviting comments. Avoid stacking multiple CTAs in one post.
- **Avoid:** thread-style bullet dumps with no narrative; a hook that's
  really a title ("5 Things About X:") reads as listicle spam here more than
  it used to.

## Sources

House-voice rules and the per-platform format table are grounded in Mesh
Pilot's `SOCIAL_CONTENT_POLICY.md` (2026 review), the Instagram caption logic
in `glitch_signal/influencer/caption.py` (2200-char cap, hashtag dedupe,
disclosure handling), the TikTok caption rules embedded in
`glitch_signal/agent/nodes/caption_writer.py` (2000-char cap, 80-char hook
window, 3–8 lowercase hashtags), and Section IX/X of
`glitch-executor-social.md` (per-platform char caps, link placement, hook
formulas). YouTube Shorts guidance is authored from current platform best
practice — no dedicated internal doc existed for it.
