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

The cron then retried "Drawdown Explained" **four times in one day**. Defects 2 and 3 are closed and
the rules below are the generalisation.

### ⚠️ Defect 1 was WRONG — renders bill CREDITS, not the wallet (corrected twice, 2026-09-02)

The wallet was first reported as *the* root cause, then downgraded to a suspect. It is now
**eliminated**: the account's own usage screen shows Video Agent renders billing **plan credits** —
"Glitch Executor: The Payout Truth" (~38s, the last successful render) cost **26 credits** — against
**1,091 credits remaining**. The USD wallet is not the render budget, so a $1.05 wallet never
blocked anything.

Everything tested, each with a real submitted session:

| Hypothesis | Test | Result |
|---|---|---|
| Bad prompt | old vs. new experiment-backed prompt | both fail identically |
| Reference files unreachable | `GE_SOCIAL_REFERENCE_URLS` is **empty** | not a factor |
| Broken brand kit | failures predate it; ran with and without | no difference |
| Agent minting a *bespoke* avatar | pinned an existing **trained** look | fails identically |
| Avatar training failure | all 50 private looks | `completed`, `error: null` |
| Credits/wallet exhausted | balances before/after a failed render | **unchanged — nothing billed**; 1,091 credits free |
| Stale MCP token | separate surface (REST key, not MCP) | unrelated |

Every failure is identical: `status: failed`, `progress: 0`, within 50–70s, `failure_code` and
`failure_message` **null on both session and video**, session-videos list empty, video record a bare
stub. HeyGen surfaces no diagnosable reason at all, and a failed render is **never billed**.

### The render step is broken account-side — proven (2026-09-02)

Two experiments close this out:

**1. The plan succeeds; the RENDER fails.** Run in `mode: "chat"`, the agent reached
`waiting_for_input` at 70s having produced a real blueprint (a `model`/`resource` message: *"I've
put together a plan for your trading-tools video…"*). The approval
(`POST /v3/video-agents/{id}` `{"message": "Looks good — go ahead and generate the video."}`)
returned **200** with a `run_id`. Ten seconds later: `failed`, `progress: 0`. So scripting, scene
planning and the approval handshake all work — only rendering dies.

**2. A bare-minimum request fails identically.** `{"prompt": "Create a 15-second video about morning
coffee."}` — no avatar, no brand kit, no glossary, no files, no orientation, unrelated subject —
also `failed` at `progress: 0`. **Nothing about our payload, prompt, brand or configuration is
involved.**

**3. Memory injection is not the cause.** That coffee video came back "tailored to your confident
operator style" — HeyGen injects workspace memory by default. Re-run with `incognito_mode: true`
(memory injection and extraction disabled): **fails identically**.

**4. The session never reaches `generating`.** It goes `thinking` → `failed` (or
`waiting_for_input` → `failed`), skipping the `generating` state entirely — the render is never
entered, let alone attempted. Following HeyGen's own troubleshooting advice ("check messages for
error details") yields nothing: no message of `type: "error"` is ever produced. The blueprint
resource IS retrievable (`resource_type: "blueprint"`, `source_type: "generated"`), confirming the
planning half completed cleanly.

Combined with 1,091 credits free and failed renders never being billed, this is an **account/vendor
-side failure of the Video Agent render step**, not something fixable in this repo.

#### Support ticket — ready to send

> Video Agent renders have failed 100% since 2026-09-01 (last success 2026-08-30, "Glitch Executor:
> The Payout Truth", 26 credits). Every session fails at `progress: 0` within 50–120s.
> `failure_code` and `failure_message` are **null on both the session and the video**, the video
> record is a bare stub, and `GET /v3/video-agents/{id}/videos` returns `[]`, so there is no
> diagnosable reason on our side.
>
> The agent plans successfully — in `chat` mode it produces a full storyboard/blueprint and reaches
> `waiting_for_input`; approving it returns 200 with a `run_id`, and the session fails ~10s later.
> Only the render step fails.
>
> Ruled out here: the prompt (a bare `{"prompt": "Create a 15-second video about morning coffee."}`
> fails identically), attachments (none), brand kit/glossary (failures predate them; identical with
> and without), avatar (a pinned pre-trained look fails the same, and all private looks report
> `status: completed`, `error: null`), and credits (1,091 remaining; balances unchanged either side
> of a failed render).
>
> Failed session ids: `a5c50c16f3214a2a9a4caf4e0eeeb298`, `b8374692…`, `a718fa61…`, `abbb6ec9…`,
> `f6777656…`, `a2f56d5274284937ad4407f35e6ca8ca`, `2dc60d2f738e4c0ab74e361dd62b2121`,
> `78ff3c6b6ce14a1782877396d6c15e76` (chat mode), `c265837720d14ecf9e212634aa55032e` (minimal),
> `643062d5e99e49069a16e0e30be90019` (minimal + `incognito_mode: true`).
>
> The session never enters `generating` — it goes straight from `thinking` (or `waiting_for_input`)
> to `failed`, so the render is never entered. No message of `type: "error"` is produced.

#### On the accept step

`mode: "generate"` (what the pipeline uses) auto-proceeds past the blueprint — confirmed in the docs
and consistent with what we observe, since generate-mode sessions die at the same point without ever
pausing. `mode: "chat"` pauses at `reviewing`/`waiting_for_input` and resumes on **any** follow-up
message (there is no `auto_proceed` parameter). We deliberately do **not** use `chat` in the cron
path: nothing would be there to approve it, and `waiting_for_input` on an unattended run is treated
as a failure. Adding a blueprint-review step is a possible future quality lever, not a fix for this.

`preflight()` now gates on **plan credits** (`HEYGEN_MIN_CREDITS`, default 26 = one render), fails
open on an unreadable balance, and passes on the live account. An earlier version gated on the USD
wallet and would have refused every render this plan can comfortably fund.

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

**Provisioned for Glitch Executor (2026-09-02)** — set these three pins (`env set` only CREATES,
it will not update an existing var):

| Env var | Value | What it is |
|---|---|---|
| `GE_HEYGEN_BRAND_KIT_ID` | `b73d42167efa4ea8a6d9375f26884f97` | imported from `glitchexecutor.com` |
| `GE_HEYGEN_BRAND_GLOSSARY_ID` | `ee36655213ca4bfb8708d287eafb7576` | 9 terms, audio-only respellings |
| `GE_HEYGEN_AVATAR_ID` | `ea2627db57f24e9fb137c826bdb29a38` | "Trader Avatar" look, portrait, trained |

The kit imported the real brand — `#93FF00` (neon), `#0a0d12` (near-black), `#FFFFFF`; JetBrains
Mono + Space Grotesk; one logo.

⚠️ **The kit settles at `status: "error"`, reproducibly** (two independent imports of the same URL).
All assets land correctly but **no roles are assigned**, and `PATCH` returns `409` while a kit is
`loading` or `error`, so roles cannot be set by hand. HeyGen **still accepts the id** on
`POST /v3/video-agents` (no `400`), which matches the documented "kit still exists/usable with
whatever assembled". Assigning roles needs the kit to reach `completed` first.

Glossary terms cover the brand name and the platform names TTS mangles: `Glitch Executor` /
`GlitchExecutor` / `glitchexecutor.com`, `cTrader`, `DXtrade`, `MT4`, `MT5`, `FTMO`, `P&L`.

⚠️ **`avatar_id` needs a LOOK id, not a group id.** `GET /v3/avatars` returns avatar *groups*;
passing one is rejected with `400 invalid_parameter — Avatar not found or you don't have access`.
Resolve the look with **`GET /v3/avatars/looks?ownership=private&group_id=…`** and pass its `id`.
That endpoint also carries per-look `status` / `error` (training state), which is the only place
avatar training failures are visible.

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

### Cost — credits, and the rate we cannot yet price

Video Agent renders bill **plan credits**. Measured from the account's usage history: **26 credits**
for a ~38s clip. The plan grants **600 credits/month** (resets on the 30th) plus **rollover** (491),
so 1,091 available ≈ 40 more renders. **A failed render costs nothing** — verified by reading the
balances either side of one.

Read the balance from **`GET /v2/user/remaining_quota` → `details.plan_credit`**. Two traps:

- The top-level **`remaining_quota` (63) is a different, much smaller API pool** — not the render
  budget. `reconcile.py` reconciled against it for months.
- ⚠️ **`GET /v3/users/me` does NOT expose credits for this account** — only the USD `wallet`. No v3
  endpoint does (`/v3/users/me/credits`, `/v3/credits`, `/v3/users/me/usage` all 404). So the
  endpoint HeyGen **removes on 2026-10-31** is currently the only source of the number that decides
  whether a render can run. **Re-check for a v3 equivalent before that date.**

The USD `wallet` (billing_type `wallet`, $1.05, auto-reload off) exists but is **not** what renders
draw on. Do not gate video on it.

**Credit rate: $0.065** — the plan costs **$39/month** for **600 credits** (operator, 2026-09-02),
so 39/600 = $0.065/credit. At the measured 26 credits/render that is **~$1.69 per video**, which
independently matches the v1 monorepo UGC lane's "~$1–2 per ad" after 22 iterations. Override with
`COST_HEYGEN_CREDIT_USD` if the plan changes. (It defaulted to 0.30 — a pay-as-you-go assumption
that priced a 30s render at $7.80 and implied ~$180/month of value inside a $39 plan.)

`heygen_cost()` now defaults to the measured **26 credits/render** (it defaulted to 1, understating
every render 26x — same class of error as the MUapi unit mistake, found the same way: by reading the
vendor's own billing screen instead of trusting the constant).

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

**MCP** — `https://mcp.heygen.com/mcp` (`AGENT_MCP_SERVERS`, `oauth: heygen`), **112 tools**,
re-authed 2026-09-02; access token ~10 days. The auth server is `https://api2.heygen.com`
(`/v1/oauth/{authorize,token,register}`, PKCE S256). ⚠️ Cloudflare **error 1010 blocks
`Python-urllib`** there — dynamic registration and the token exchange both 403 with it, while
`curl`/`httpx` pass; reuse the existing public client id rather than re-registering. This is a
SEPARATE surface from the Video Agent REST path above and shares only the account.

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
