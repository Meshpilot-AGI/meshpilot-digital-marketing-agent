# CONTENT-CLAUDE — content-pipeline text generation on Claude (MUapi = image/video only)

**Status:** SHIPPED 2026-08-30 (verified live on Sonnet 5 + Haiku 4.5)  ·  **Owner:** Claude

> **Gotcha found + fixed during build:** Haiku 4.5 (the `cheap` tier) **rejects `output_config.effort`**
> (400) — it's a Claude-5-family param. `_apply_effort` now skips effort for Haiku, so all
> cheap-tier content calls work. (Sonnet 5 still gets effort=low.)
**Follows:** FILES (brand documents). See `docs/vendors/anthropic.md`.

## Why + scope (operator)

`agent/llm.py::chat()` routes ALL content-pipeline **text** generation through MUapi/Gemini. Move
**all of it to Claude**; **MUapi stays only for image/video generation** (`media/generation/` +
recipes — a separate path, untouched). This unifies text on our primary model, and lets
`caption_writer` ground captions in a brand's uploaded style guide (Files API, Claude-only).

Text callers moved by the single `chat()` rewrite: `caption_writer`, `scout`, `script_writer`,
`text_writer`, `storyboard`, `carousel_gen`, `quote_card`, `content_router`, `influencer/*`
(`complete_with_fallback`). Image/video (`MuapiEngine` via `media/generation`) is NOT touched.

## What changes

### 1. `agent/llm.py` — `chat()` → Claude
Rewrite the text shim to call `agent/loop/llm.py::complete_messages` (which already accepts
OpenAI-style messages, converts multimodal `image_url` blocks, passes native `document`/`image`
blocks through, and meters to the per-brand budget). Drop the `MuapiEngine` text path.
- `model_for(tier)` maps tiers to **Claude** models: `cheap` → `claude-haiku-4-5-20251001`,
  `smart` → `claude-sonnet-5` (env overrides `AGENT_CONTENT_MODEL_CHEAP` / `_SMART`, and the
  existing per-tier `AGENT_CONTENT_TEXT_MODEL_<TIER>`).
- `chat(messages, *, tier, max_tokens, temperature, model, client)` → `complete_messages(messages,
  model=model or model_for(tier), max_tokens=max_tokens, client=client)`. `temperature` accepted
  but not forwarded (current-gen 400s on it). `client` injectable for tests (replaces `engine`).
- `complete_with_fallback` unchanged (still wraps `chat`, still returns the `(llm error: …)`
  sentinel).

### 2. `agent/nodes/caption_writer.py` — brand-doc grounding
Both caption paths call a new `_caption_llm(system_prompt, user_text, brand_id)` seam that prepends
the brand's uploaded `document` blocks (`documents.list_for_brand(brand_id)`) to the user content,
then `chat(..., tier="smart")` (Sonnet 5 — captions are the product). No docs → no blocks (still
works). JSON contract unchanged; `except → {}` template fallback stays.

## Verification
- Unit: rewrite the MUapi-routing tests (`test_chat_routes_to_muapi_text` → asserts Claude routing
  via an injected client; `model_for` returns Claude ids). Repoint the 4 caption mocks from
  `agent_llm.chat` → the `_caption_llm` seam; add a doc-block-grounding test. Full suite green.
- **Live (real Sonnet 5)**: (a) `chat([...], tier="smart")` returns text via Claude; (b) upload a
  brand guide → `caption_writer` produces a caption that obeys the guide + parses as JSON, metered
  as a Claude call.

## Risks / mitigations
- **Cost ↑** across text nodes (Gemini-flash → Haiku/Sonnet). Bounded by the per-brand budget gate;
  `cheap` tier = Haiku 4.5 ($1/$5); models env-overridable. If needed, a per-node tier stays cheap.
- **JSON reliability** — nodes that expect JSON already tolerate wrapped JSON + have fallbacks;
  Claude at effort=low returns clean JSON.
- **Images** — nodes passing `image_url` now hit Claude vision (Sonnet 5) via `complete_messages`
  conversion; verify any vision-using node still works.

## Out of scope (later)
Structured outputs for guaranteed JSON; citations; per-node model tuning; moving image/video off
MUapi (never — MUapi is the image/video path).

## Write-back
`docs/vendors/anthropic.md`, `control-plane/ACTIVE_LANE_BOARD.md`, `control-plane/ENGINEERING_SUPERVISOR.md`.
