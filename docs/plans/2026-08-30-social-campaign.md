# SOCIAL-CAMPAIGN — autonomous, conscience-gated social posting

**Status:** DESIGN (approved 2026-08-30) · **Owner:** Claude · **Lane:** `lane/social-campaign`

> Goal (operator): the agent should, on its own, find a content idea for GE, generate an
> image (Higgsfield) and a video (HeyGen), and post **one** piece to each platform —
> X, LinkedIn, TikTok, Facebook, Instagram (**no YouTube**) — with **no human in the
> loop**, safely and repeatably.

This capability turns that into a first-class, deterministic, testable pipeline instead of a
raw `full`-scope agent run. The creative choices (the idea, the captions) use the LLM; every
step that must be **exact and safe** (media mapping, the conscience hold, per-platform
fan-out, dedup, cost) is deterministic code.

---

## Why not the existing paths

- **Stock pipelines can't reach the tools.** Per `agent/loop/scopes.py`, only scope `full`
  offers discovery + media + HeyGen + Higgsfield + publish together; `content` has Higgsfield
  but not HeyGen, discovery, or publish. A `full`-scope directed run *could* do it, but the
  ReAct loop would decide the fan-out — "exactly 1/platform, image-here/video-there,
  gate-then-publish, no dupes" would be hoped-for, not guaranteed, and conscience-gating
  mid-loop is awkward (the critic reviews final output, not each tool call).
- **So we build a deterministic orchestrator** that calls the same building blocks (media
  factory, conscience, publishers, memory, cost meter) in a fixed, tested order.

---

## Isolation — one capability among many (non-negotiable)

This is **one** of the agent's tasks/capabilities, not its workflow. The agent stays a
general, multi-tool, multi-capability agent; `social_campaign` sits beside `curate`,
`drive_scout`, `reconcile`, `routing_audit`, and future capabilities — nothing about the
core is hardcoded to social posting.

- **Additive only.** Do NOT modify the ReAct loop (`agent/loop/runner.py`), the default scope,
  the general tool registry, or any other capability. The only shared-surface touches are:
  two new config flags, one new cron-registry entry, and one additive migration.
- **Self-contained.** All social logic lives under `src/glitch_signal/agent/social/`. The
  fixed platform/media mapping, routing, and recipe choices are internal to that package.
- **Reuse, don't fork.** It calls the shared building blocks (media factory, conscience,
  memory, publishers, budget, LLM) as they are — it must not special-case them for social.
- **No behavior change when disabled.** With `agent_social_enabled=False` (default) the agent
  behaves exactly as before; the capability is inert and invisible to every other path.

## Decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| Safety model (no HITL) | **Conscience as a hard gate** — `escalate` → held as draft (not posted); `pass`/`concerns` → publish |
| Trigger | **Recurring self-cron** (existing `agent/cron`); operator sets cadence; ships inert |
| Media mapping | **1 video → TikTok + Instagram**; **1 image → X + LinkedIn + Facebook** (1 idea, 2 generations) |
| Video method | **HeyGen Video Agent** — prompt-driven, **B-roll + subtitles, NO avatar/talking-head**; **portrait**; fed **brand assets + platform screenshots** as reference files |
| Image method | **Higgsfield** via the existing `higgsfield-soul-image` recipe (media factory) |
| Build shape | **Deterministic capability** (LLM for idea, captions, and the video prompt only) |
| Platforms | X, LinkedIn, TikTok (Buffer) + Facebook, Instagram (Meta). **YouTube excluded.** |

### Video — HeyGen Video Agent (no avatar)

The video is produced by HeyGen's **Video Agent** (prompt→video), which selects B-roll, adds
text overlays/subtitles, music, and pacing on its own. We do **not** use a talking-head avatar.

- **API:** `POST https://api.heygen.com/v3/video-agents` (`X-Api-Key: $HEYGEN_API_KEY`), body
  `{prompt, orientation:"portrait", mode:"generate", files:[{type:"url", url:…}]}`. Async:
  response gives `session_id`; poll `GET /v3/video-agents/{session_id}` until `video_id` is set,
  then `GET /v3/videos/{video_id}` until `status=completed` → `video_url`. (~5–10× the clip
  length to render; fine on a background run.)
- **Reference files = OUR inputs:** brand assets + platform screenshots, supplied as URLs via
  `brand_env("SOCIAL_REFERENCE_URLS")` (comma-separated; owner-controlled). Up to 20 files;
  png/jpeg/mp4/pdf.
- **Prompt craft** (per HeyGen's guidance): a natural, first-person **story** script + a **tone**
  line + `orientation: portrait`; **positive framing** (describe what we want, never "no
  B-roll"); no timestamps/scene-structure; no question-driven scripts.
- **Isolation:** this is a **self-contained client** in `agent/social/video.py` — it does **not**
  add an engine/recipe to the shared media factory (the factory's avatar `heygen.py` engine is a
  different HeyGen product and is left untouched). It reuses only `storage.persist`-style bucket
  upload and the cost meter.

---

## Module structure — `src/glitch_signal/agent/social/`

- `spec.py` — dataclasses: `Idea` (angle, hook, key_points, dedup_key), `PostDraft`
  (platform, media_kind, media_url, caption), `PlatformResult` (platform, status,
  verdict, platform_post_id, post_url, error), `CampaignResult` (campaign_id, idea,
  image_url, video_url, posts: list[PlatformResult], cost_usd, skipped_reason?).
- `ideate.py` — `async propose_idea(brand_id, *, complete, recent_keys) -> Idea | None`.
  Recalls discovery notes + verified brand facts, asks the LLM (router `complex`) for one
  idea as strict JSON, returns `None` if it collides with a recent `dedup_key`.
- `captions.py` — `async write_captions(brand_id, idea, *, complete) -> dict[str, str]`.
  Two variants (`image`, `video`) in GE voice, each passed through `polish_copy`
  (mandatory content-policy pass), then deterministic per-platform length trims.
- `video.py` — **self-contained HeyGen Video Agent client** (isolation: not a media-factory
  engine). `build_video_prompt(idea) -> str` (natural story + tone + `orientation: portrait`,
  positive framing) and `async generate_video(brand_id, prompt, file_urls, *, submit, poll) ->
  str` (POST `/v3/video-agents`, poll session→`video_id`→`/v3/videos/{id}`, then persist to the
  brand bucket + meter). `reference_urls(brand_id) -> list[str]` reads
  `brand_env("SOCIAL_REFERENCE_URLS")`.
- `campaign.py` — `async run_campaign(brand_id, *, deps…) -> CampaignResult`. The
  orchestrator (below). All external effects injected for tests.
- Registered in `agent/cron/capabilities.py` as capability **`social_campaign`** so the
  self-cron can run it.

**Reused as-is (no changes beyond seams):** `media.generation.generate` + `persist` (Higgsfield
**image only**), `agent/loop/conscience.py::review` + `brand_facts`, `platforms/buffer.py`,
`platforms/facebook.py`, `platforms/instagram.py`, `analytics/cost/budget.py` + the cost meter,
`agent/memory/store.py` (`recall`/`remember`), `agent/loop/routing.py` (via the LLM seam),
`media/generation/storage` (bucket persist for the HeyGen output). **Not touched:** the media
factory's avatar `heygen.py` engine (a different HeyGen product).

**Reference assets (owner-curated, hosted in the brand's Supabase bucket):** the brand's logo +
platform screenshots live under the brand bucket (e.g. `ge-media/reference/`); their public URLs
are listed in `brand_env("SOCIAL_REFERENCE_URLS")` (comma-separated) and passed to the Video
Agent as `files`. Owner uploads the curated set at enablement.

---

## The flow — `run_campaign(brand_id)`

Deterministic except steps 2 and 4 (LLM). Every step fail-soft; a failure in one platform
never aborts the others; any uncertainty resolves **toward not posting**.

1. **Preconditions.** `agent_social_enabled` AND `agent_publish_enabled` on, and
   `budget.check(brand_id)` passes. (Media generation here is governed by this capability's own
   master flag + budget/caps — **not** the content pipeline's `agent_content_media_enabled`,
   which only selects that pipeline's scope.) Otherwise return a no-op
   `CampaignResult(skipped_reason=…)`.
2. **Ideate.** `propose_idea()` — recall discovery/trend notes + verified brand facts, LLM
   returns one idea; dedup against recent `social_campaign.dedup_key` (last N). No fresh
   idea → skip (recorded).
3. **Generate media (2 calls).** **Image:** Higgsfield via the media factory
   (`generate(Brief(recipe="higgsfield-soul-image"))` + `persist`). **Video:** the HeyGen
   **Video Agent** via `video.generate_video(brand_id, build_video_prompt(idea),
   reference_urls(brand_id))` — prompt + brand/screenshot reference files → B-roll+subtitles
   video, persisted to the bucket. **Per-medium fail-soft:** video fails → image-group posts
   still proceed; image fails → video-group posts still proceed; both fail → skip.
4. **Captions.** `write_captions()` → `{image, video}`, polished, per-platform trimmed.
5. **Conscience gate.** For each intended post, `conscience.review(goal, output=caption(+idea
   context), facts=brand_facts)`. `escalate` → **held** (`social_post.status=held`, not
   posted); `pass`/`concerns` → allowed. If the constitution is absent (`review` returns
   `{}`), treat as **allowed** (matches current advisory semantics) — documented, revisitable.
6. **Fan-out publish (exactly 1/platform).** For each allowed post, deterministic route:
   - Buffer: **X** (image), **LinkedIn** (image), **TikTok** (video).
   - Meta: **Facebook** (image), **Instagram** (video).
   Idempotency: a unique `(campaign_id, platform)` key + a pre-publish check of existing
   `social_post` rows, so a retry/re-run never double-posts.
7. **Record.** Persist the `social_campaign` row + one `social_post` per platform (status:
   `posted` / `held` / `failed` / `skipped`), metered cost, and `remember` a short episode.
   Return `CampaignResult`.

---

## Data model — one migration

`supabase/migrations/<ts>_social_campaign.sql` (RLS deny-all, naive-UTC, matches convention):

```
social_campaign(
  id uuid pk, brand_id text not null, dedup_key text not null,
  idea jsonb not null, image_url text, video_url text,
  status text not null default 'draft',           -- draft|posted|partial|held|failed|skipped
  cost_usd numeric, created_at timestamptz default now())
-- index (brand_id, created_at desc); (brand_id, dedup_key)

social_post(
  id uuid pk, campaign_id uuid not null references social_campaign(id),
  platform text not null, media_kind text not null,   -- image|video
  caption text, verdict text,                          -- pass|concerns|escalate
  status text not null,                                -- posted|held|failed|skipped
  platform_post_id text, post_url text, error text,
  created_at timestamptz default now(),
  unique (campaign_id, platform))                      -- idempotency
```

---

## Config + flags (`config.py`)

- **`agent_social_enabled: bool = False`** — master switch; the capability no-ops unless on.
- Reuses existing gates: `agent_publish_enabled`, media allowance, `agent_discovery_enabled`
  (for fresh trend notes; without it, ideation leans on brand facts), budget
  (`brand_env("DAILY_BUDGET_USD")`).
- **`agent_social_max_posts_per_run: int = 5`** — hard cap (the 5 platforms).
- Media mapping + platform list default in code
  (`{video: [tiktok, instagram], image: [x, linkedin, facebook]}`), per-brand overridable via
  `brand_env` / brand config. Recipe slugs for the image/video default in config.

Ships **inert**: flag off + no seeded cron job → nothing runs, nothing posts.

---

## Scheduling

Registered as the `social_campaign` capability. Runs via the existing self-cron
(`agent_cron_enabled`): seed a `capability` job `{name: "social_campaign"}` on a cadence via
`POST /internal/agent/cron` (jobs-auth), or one-shot. Operator owns the cadence and can pause
it. No new scheduling machinery.

---

## Error handling & guardrails

- **Budget** checked before ideation and before each paid action; at/over cap → skip that step.
- **Conscience hard-gate**: `escalate` never publishes; LLM/critic errors resolve to **held**.
- **Per-medium fail-soft** and **per-platform fail-soft** (one failure ≠ whole-run abort).
- **Dedup** (recent `dedup_key`) + **idempotency** (`unique(campaign_id, platform)`).
- **Per-run cap** = `agent_social_max_posts_per_run`.
- Cost metered through the existing `usage_events` choke points; a run's total recorded on the
  campaign row.
- SSRF: media URLs handed to publishers already come from our own bucket; any model-supplied
  URL still goes through the existing `assert_safe_media_url` guard.

---

## Testing (TDD, no network)

Inject fakes for: LLM (`complete`), media engines (return fake asset URLs; one variant to
simulate video-fail), conscience (return `pass` / `escalate`), publishers (record calls),
budget, and the DB engine (the `FakeEngine` pattern from `tests/test_agent_memory.py`).
Assertions:
- Exactly **1 post per platform**, correct **media mapping** (video→TikTok/IG, image→X/LI/FB).
- **`escalate` → held, never published** (publisher fake not called for that platform).
- **Dedup**: a repeated idea key → run skips (no generation, no posts).
- **Partial media failure**: video fails → only image-group posts; image fails → only
  video-group; both fail → skip.
- **Idempotency**: a re-run with the same campaign key doesn't double-post.
- **Preconditions**: flags off / budget over → no-op with reason, no external calls.
- **Cost** recorded on the campaign row.

Acceptance: `uv run pytest -q` green (new `tests/test_social_campaign.py`), 0 new ruff debt,
and the capability importable + registered. **No prod flags flipped in this lane.**

---

## Out of scope (follow-ons)

Per-platform bespoke media, analytics/engagement pull-back, A/B of angles, multi-brand tuning,
a held-drafts review UI, and enabling it live in prod (a separate, deliberate enablement step).
