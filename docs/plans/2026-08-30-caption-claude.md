# CAPTION-CLAUDE — move caption generation to Claude + brand-doc grounding

**Status:** design (awaiting build)  ·  **Opened:** 2026-08-30  ·  **Owner:** Claude
**Follows:** FILES (brand documents). See `docs/vendors/anthropic.md`.

## Why

`caption_writer` generates captions through **MUapi/Gemini** (`agent/llm.py::chat()`), so it can't
use the Files API (Claude-only) to follow a brand's uploaded style guide. Moving *caption
generation* to Claude (Sonnet 5) lets captions (a) be grounded in the brand's uploaded documents
and (b) run on our primary, more capable model. **Scope: `caption_writer` only** — the rest of the
content pipeline (scout, script_writer, text_writer, storyboard, carousel_gen, quote_card,
influencer) stays on MUapi for now (moving all of it is a separate cost decision).

## What changes (~1 node + tests)

### `agent/nodes/caption_writer.py`
- New single seam **`_caption_llm(system_prompt: str, user_text: str, brand_id: str) -> str`** that
  both caption paths (`_generate_via_catalog` ~L352 and `_generate_via_filename` ~L384) call
  instead of `agent_llm.chat(...)` directly.
- **Provider switch** (`AGENT_CAPTION_PROVIDER`, default `claude`; `muapi` = the old path for a
  no-deploy revert):
  - **claude:** fetch the brand's uploaded docs (`documents.list_for_brand(brand_id)`) → build
    `document` blocks → user content = `[<doc blocks>…, {"type":"text","text": user_text}]` →
    `complete_messages([{system}, {user}], model=AGENT_CAPTION_MODEL (default claude-sonnet-5),
    max_tokens=4096)`. The uploaded style guide now grounds the caption **in addition to** the
    existing `voice_prompt_path` `{voice}` slot.
  - **muapi:** the current `agent_llm.chat(...)` (no doc grounding).
- The JSON contract is unchanged (`_parse_caption_json`); Claude at effort=low returns clean JSON
  (no thinking) just like the ReAct loop. The existing `except → {}` fallback stays (resilient:
  a Claude failure falls back to the template caption).
- **Cost:** captions move from Gemini-flash to Sonnet 5 ($2/$10 /MTok). `complete_messages` already
  meters to the per-brand budget (COST-METER). Model is env-overridable (e.g. Haiku 4.5 for cheap).

## Verification
- Unit: the 4 caption tests currently patch `caption_writer.agent_llm.chat` → repoint them at the
  new seam `caption_writer._caption_llm`. New tests: claude path builds `document` blocks from the
  brand's docs (mock `documents.list_for_brand` + `complete_messages`); `AGENT_CAPTION_PROVIDER=muapi`
  still routes to `agent_llm.chat`; no-docs case still generates (no doc blocks).
- **Live (real Sonnet 5)**: upload a brand style guide → run `caption_writer` for a signal → the
  returned caption obeys the guide (e.g. avoids a forbidden word / matches the tone) and parses as
  JSON. Confirm the meter records a Sonnet 5 caption call.

## Risks / mitigations
- **Cost per caption ↑** — bounded by the per-brand budget gate; `AGENT_CAPTION_MODEL` can drop to
  Haiku 4.5; `AGENT_CAPTION_PROVIDER=muapi` reverts instantly (no deploy).
- **JSON reliability** — Claude follows "Return JSON ONLY"; `_parse_caption_json` already tolerates
  fenced/prose-wrapped JSON, and the `except → {}` template fallback covers a miss.
- **Brand-doc isolation** — reuses `documents.list_for_brand` (scoped `WHERE brand_id`); file_ids
  never come from caption input.

## Out of scope (later)
Moving the other content nodes to Claude; structured-output (`output_config.format`) for guaranteed
JSON; citations; injecting docs into script/text_writer.

## Write-back
`docs/vendors/anthropic.md`, `control-plane/ACTIVE_LANE_BOARD.md`, `control-plane/ENGINEERING_SUPERVISOR.md`.
