# HeyGen — knowledge base (video, API v3)

Everything the agent needs to produce **production-grade video** on HeyGen. Two sources, kept
distinct on purpose:

- **DOC** — verified at `developers.heygen.com` (2026-09-02). The full page index lives at
  `https://heygen-1fa696a7.mintlify.site/llms.txt`; every page also serves a plain-markdown `.md`.
- **LIVE** — probed against our own account the same day. Where LIVE contradicts DOC, LIVE wins and
  the contradiction is called out, because that gap is what broke production.

Implemented by `agent/social/video.py` (Video Agent, the social path) and
`media/generation/engines/heygen.py` (avatar engine). Base `https://api.heygen.com`, auth
`X-Api-Key`.

---

## 0. The incident this knowledge base exists to prevent

Between 2026-09-01 and 09-02, **five consecutive nightly campaigns produced no video.** Every
Video Agent session failed at `progress: 0`, and the log line for each was:

```
social.video_failed error="heygen video <id> failed: "
```

Three separate defects stacked up, none of which was the prompt:

| # | Defect | Why it was invisible |
|---|---|---|
| 1 | **The wallet held $1.05**, auto-reload off, against ~$1–2 per render | HeyGen accepts the session, then fails it with no reason |
| 2 | We read `error`/`message` off the video — **fields HeyGen does not define** | every failure logged an empty reason |
| 3 | We polled only the **video**, but a session can die before a `video_id` exists | a dead run still burned the full poll timeout |

The cron then retried "Drawdown Explained" **four times in one day** against an empty wallet. All
three are now closed; the rules below are the generalisation.

> **Check the wallet first.** When video stops working, `GET /v3/users/me` before reading any code.

---

## 1. Video Agent — the contract

One prompt in, a finished multi-scene video out; the agent writes the script, picks the avatar and
voice, sources b-roll, composes scenes and renders. Composition is authored via **Hyperframes**
(HTML→video), so the agent builds layouts rather than filling a template.

| Call | Purpose |
|---|---|
| `POST /v3/video-agents` | create a session |
| `GET /v3/video-agents/{session_id}` | poll status / get `video_id` / read `messages` |
| `POST /v3/video-agents/{session_id}` | send a message or request a revision (`chat` mode) |
| `POST /v3/video-agents/{session_id}/stop` | halt |
| `GET /v3/videos/{video_id}` | render status and `video_url` |
| `GET /v3/video-agents/styles` | list curated visual styles |
| `GET /v3/users/me` | wallet balance |

⚠️ The revision endpoint is `POST /v3/video-agents/{session_id}` with a **`message`** field. The
older `/messages` sub-path used by the archived monorepo UGC lane is **not** the current API.

### Request body — `POST /v3/video-agents`

`additionalProperties: false` — **an unrecognised field is rejected with 422**, so never send a key
speculatively and never send `null` for a pin you don't have.

| Field | Type | Notes |
|---|---|---|
| `prompt` | string, **required** | 1–10,000 chars |
| `mode` | `generate` \| `chat` | default `generate` (one-shot). `chat` pauses for storyboard review |
| `orientation` | `portrait` \| `landscape` | auto-detected if omitted — **always set it** |
| `avatar_id` / `voice_id` | string | pin the presenter; auto-selected (randomly) if omitted |
| `style_id` | string | curated visual template from the styles endpoint |
| `brand_kit_id` | string | brand colors, fonts, logo |
| `brand_glossary_id` | string | pronunciation of custom terms (audio only; captions keep spelling) |
| `files` | array | **max 20**; png, jpeg, mp4, webm, mp3, wav, pdf |
| `callback_url` / `callback_id` | string | webhook instead of polling |
| `incognito_mode` | bool | default `false`; disables memory injection/extraction |

`files` entries are a discriminated union — **32 MB per file, including URL inputs**:

```json
{"type": "url",      "url": "https://…"}
{"type": "asset_id", "asset_id": "asset_…"}          // from POST /v3/assets
{"type": "base64",   "media_type": "image/png", "data": "iVBOR…"}
```

### Status vocabularies

The **create** response and the **get-session** response use *different* enums — the read side is a
superset. Handle all six:

| Session status | Meaning |
|---|---|
| `thinking` | scripting / composing / preparing the storyboard |
| `reviewing` | paused at a review checkpoint (`chat` mode) |
| `waiting_for_input` | paused, waiting on **you** |
| `generating` | rendering |
| `completed` | done |
| `failed` | dead |

Session also carries `progress` (0–100) and `messages` (max 40, **newest-first**; each has `role`
∈ `user`/`model`, `type` ∈ `text`/`resource`/`error`, `content`, `resource_ids`).

Video status: `pending` → `processing` → `completed` (has `video_url`) | `failed`.

> **The session is the authority, not the video.** A session can fail before it is ever assigned a
> `video_id`. Poll the session every cycle; only consult the video once `video_id` exists.
> `waiting_for_input` on an unattended cron run is a failure — nobody is going to answer.

### Failure reporting — DOC vs LIVE

DOC: a failed video carries `failure_code` (machine-readable) and `failure_message` (human).

**LIVE: both were `null`** on a genuinely failed session *and* its video. There is frequently **no
machine-readable reason at all.** So read, in order:

1. `failure_code` / `failure_message` on the video, then the session
2. the newest session message of `type: "error"`
3. the newest `model` message, labelled as *not* a real failure reason

Never surface an empty string. `video.py::_reason()` implements exactly this ladder.

### Timing

Generation takes **5–10× the finished clip's length** (a 30s clip ≈ 3–5 min; 1 min ≈ 5–10 min).
Poll every 10–30s. Our default deadline is **900s**, clamped by `campaign.py` to stay under the cron
capability cap. Beyond 24h processing, HeyGen says contact support with the `video_id`.

Prefer the **webhook** (`callback_url`) over long polling — the receiver already exists (§5) and the
edge kills a synchronous request at 100s anyway.

---

## 2. Prompting — what actually works

HeyGen published the results of **14 controlled experiments** on this endpoint. Their findings, and
ours, both encoded in `video.py::build_video_prompt`:

**Do**

- **Write a great script.** The narration words matter more than any production instruction.
- **Add tone, not timestamps.** A tone paragraph ("like a founder on a podcast — reflective,
  honest") beats scene blocking.
- **Stories beat lists. Bold beats safe. Flow beats structure.**
- **Lead with duration**, and set `orientation` explicitly.
- Describe the presenter **affirmatively** to pin them ("one male presenter in his early thirties,
  visible throughout"). Left open, the agent re-rolls the narrator every render and the brand has a
  different face each post.

**Don't**

- ❌ **Per-scene timestamps** (`Scene 1 (0-5s)`) — "make the delivery sound robotic".
- ❌ **Questions** — unnatural from a single presenter to camera.
- ❌ **Restrictive instructions** ("no stock footage", "do NOT…") — makes the agent play safe and
  produced *visually flat* results in their tests. Say what you want instead.
- ❌ **Over-prescribed visuals** — the agent composes well when left room.

⚠️ **A documented contradiction:** `prompting-guide.md` demonstrates a fully timestamped scene
script for "exact control", while `writing-effective-video-prompts.md` explicitly warns against that
same pattern. The second page is the one backed by the 14 experiments, so **we follow it** — and it
also agrees with the archived monorepo UGC lane's own conclusion after 22 iterations.

---

## 3. Brand identity — how successive renders become one brand

Three independent, composable pins. Without them, thirty posts look like thirty companies.

| | Endpoint | What it fixes |
|---|---|---|
| **Brand kit** | `POST /v3/brand-kits {url}` | colors, fonts, logo — applied to backgrounds, text, chart palettes, logo placement. Built by importing a **website URL**; poll `status` `loading`→`completed` (usually <2 min, fonts last). Roles: colors `primary`/`secondary`/`tertiary`/`accent`, fonts `title_text`/`body_text`, logo `primary`. |
| **Brand glossary** | `POST /v3/brand-glossaries {name, terms:[{term, pronunciation}]}` | how the narrator *says* our terms. Audio only — captions keep the original spelling. Set once per session; unlike `brand_kit_id` it **cannot** be swapped mid-session. |
| **Style** | `GET /v3/video-agents/styles` | curated look: scene layout, transitions, pacing. Filter by `tag` ∈ `cinematic`, `retro-tech`, `iconic-artist`, `pop-culture`, `handmade`, `print`; each style has an `aspect_ratio` — pick a `9:16` one for social. |

Brand kit and style **compose**: the style picks the look, the brand kit makes it ours. An unknown
id is rejected at request time with `400 invalid_parameter` and **consumes no credits**.

`brand_glossary_id` supersedes the deprecated `brand_voice_id`.

Per-brand pins are read from env by `video.session_options()` and omitted when unset:
`<PREFIX>_HEYGEN_{AVATAR_ID,VOICE_ID,STYLE_ID,BRAND_KIT_ID,BRAND_GLOSSARY_ID}`.

**Not yet set for Glitch Executor** — creating the brand kit from `glitchexecutor.com` and a
glossary for the brand name is the next concrete upgrade to video quality.

Voices: `GET /v3/voices` (filter `language`, `gender`, `type`, audition via `preview_audio_url`),
then pin `voice_id`. Music: `GET /v3/audio/sounds?query=…` is semantic search; how a chosen track
attaches to a Video Agent render is **not documented**.

---

## 4. Limits, errors, cost

- **Concurrency:** 10 concurrent jobs (PAYG) — Video Agent sessions, avatar renders and
  translations share the pool.
- **Throttling:** `429` + `Retry-After`. No `X-RateLimit-*` headers documented.
- **Caps:** prompt 1–10,000 chars; ≤20 attachments; 32 MB/file; ≤30 min and ≤50 scenes per video.
- **Errors:** `{code, message, param, doc_url}`. **Retryable:** `rate_limit_exceeded`,
  `quota_exceeded`, `internal_error` (500), `service_unavailable` (503), `gateway_timeout` (504),
  `voice_provider_error` (502), `download_failed`, `resource_not_ready`, `brand_kit_not_ready`,
  `request_in_progress`. **Not retryable:** `insufficient_credit`, `subscription_required`,
  `content_policy_violation`, `invalid_parameter`, and every `*_not_found`.

### Cost and the wallet

This account is `billing_type: wallet`, currency USD. **Video Agent bills the wallet.** A render
costs roughly **$1–2** (22 iterations of the monorepo UGC lane).

`video.py::preflight()` refuses to submit below `HEYGEN_MIN_WALLET_USD` (default **$2.00**) and
raises `HeyGenCreditError` naming the balance. It fails **open** on an unreadable balance — a flaky
profile endpoint must not block every render.

> ⚠️ **`auto_reload` is disabled.** Nothing tops this wallet up on its own. Turning it on is the
> single highest-value operational fix for video reliability.

⚠️ Do **not** judge funding by `GET /v2/user/remaining_quota`: during the outage it reported a
comfortable `remaining_quota: 63` / `plan_credit: 1091` while the wallet held $1.05 and every render
was failing. That pool is not what the Video Agent draws from.

### Deprecation — acts before 2026-11-01

All v1/v2 endpoints are removed **2026-10-31**; the live v2 response now carries a warning that
names AI agents specifically. `GET /v2/user/remaining_quota` has **no documented v3 replacement** —
`GET /v3/users/me` → `wallet.remaining_balance` is the equivalent and is what
`analytics/cost/reconcile.py` now reads (`BALANCE_UNIT["heygen"] = "usd"`, no credit conversion).

Other migrations: `/v1|v2/video/generate`→`POST /v3/videos`, `/v1/video_status.get`→`GET
/v3/videos/{id}`, `/v1/video/upload`→`POST /v3/assets`, `/v1/avatar.list`→`GET /v3/avatars`,
`/v1/voice.list`→`GET /v3/voices`, `/v1/user/me`→`GET /v3/users/me`.

---

## 5. Keys, engine, webhook

**Keys** (global infra, FastAPI Cloud secrets):

- `HEYGEN_API_KEY` — account key (`sk_V2_…`), sent as `X-Api-Key`.
- `HEYGEN_WEBHOOK_SECRET` — endpoint signing secret (`whsec_…`), **shown only once** at creation or
  rotation. Until set, `POST /webhooks/heygen` fails closed (503).
- `HEYGEN_MIN_WALLET_USD` — preflight floor (default 2.0).

**Avatar engine** (`media/generation/engines/heygen.py`) — submit→poll against `POST /v3/videos`,
same contract as MUapi. `Engine.generate(model, prompt, *, params)` maps `model`→`avatar_id`,
`prompt`→`input_text`. Select per call with `{"engine": "heygen"}` (default is `muapi`).

**Webhook** (`POST /webhooks/heygen`) — registered at `https://api.meshpilot.app/webhooks/heygen`
(endpoint `903cc106770943118974f87728486f0f`). Public path, exempt from the app rate limiter.

Verification is fail-closed: `Heygen-Signature` = hex HMAC-SHA256 of the **raw body** with
`HEYGEN_WEBHOOK_SECRET`; reject on unset secret (503), missing headers (400), `Heygen-Timestamp`
older than ~5 min (400), or mismatch (401). Dedup on `Heygen-Event-Id`, then ack `200` fast.

Relevant events: **`video_agent.success`**, **`video_agent.fail`**, `avatar_video.success`,
`avatar_video.fail` (24 types total). Only `avatar_video.success` has a documented payload; for
everything else treat the event as a completion *signal* and re-fetch authoritative state.

> **Open follow-up:** the receiver verifies and logs but completion still comes from our own poll.
> Passing `callback_url` and finishing on the event would end the long-poll/timeout class of
> failure entirely.

Manage the endpoint: `GET /v3/webhooks/endpoints`, `POST /v3/webhooks/endpoints {url, events}`
(returns `secret` once), `POST /v3/webhooks/endpoints/{id}/rotate-secret`.
