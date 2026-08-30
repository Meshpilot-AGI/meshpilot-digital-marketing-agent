# Vendor runbook — Anthropic / Claude (the agent's brain)

Claude (**Messages API**) is the LLM behind the agent loop — the "messaging" path you talk
to in Discord. This runbook is the practical reference for how we call Claude, the
current-generation gotchas that bite our code, and the levers worth pulling. Verified
against `platform.claude.com/docs` + the live API on 2026-08-30. Prices/features drift —
re-verify against the docs before relying on a number here.

## How we use it

- **Primary path — the agent loop.** `src/glitch_signal/agent/loop/llm.py` (`_post` →
  `POST {AGENT_LLM_BASE}/v1/messages`, header `anthropic-version: 2023-06-01`,
  `x-api-key` = an **inference** key `sk-ant-api…`, NOT an admin key). `complete()` is one
  user turn → assistant text; `complete_messages()` accepts an OpenAI/LiteLLM-style message
  list (multimodal `image_url` blocks converted to Anthropic `image` blocks). The ReAct loop
  (`runner.py`) calls `complete(build_prompt(...), system=system_prompt())` each step and
  parses a JSON action out of the **text** (`parse_action` → `re.search(r"\{.*\}")`).
- **Model:** env **`AGENT_LLM_MODEL`** (default in code). **`AGENT_LLM_BASE`** overrides the
  API base. Effort: **`AGENT_LLM_EFFORT`** (default `low`).
- **Cost metering:** every call is attributed to the active brand via `_meter` →
  `analytics/cost/pricing.py::anthropic_cost` (COST-METER). The price book already accounts
  for `cache_read_input_tokens` / `cache_creation_input_tokens`.
- **Second, separate path — GE narratives** run on **Bedrock Converse** (a different SDK;
  see the Converse gateway). ⚠️ Bedrock lacks the Files API + MCP connector and is
  **base64-only** for images — the notes below are for the first-party Messages API.

## Models (current generation)

| Model | API id | Context | In / Out $/MTok | Notes |
|---|---|---|---|---|
| Claude Sonnet 5 | `claude-sonnet-5` | 1M | **$2 / $10** | Our loop default. Best speed/intelligence for a chat agent. |
| Claude Opus 5 | `claude-opus-5` | 1M | $5 / $25 | Reach for the hardest planning only. |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 200K | $1 / $5 | Cheap/fast tier for mechanical sub-steps. |
| Claude Fable 5 | `claude-fable-5` | 1M | $10 / $50 | Longest-horizon agents; overkill for us. |

Model-tiering (matches the repo doctrine): **Sonnet 5** for the loop/planning, **Haiku 4.5**
for cheap mechanical sub-steps, **Opus 5** only for the hardest turns. Sonnet 5's $2/$10 is
now the permanent price (the scheduled $3/$15 increase was cancelled).

## ⚠️ Current-generation breaking changes (these bite our code)

1. **Sampling params are rejected.** `temperature` / `top_p` / `top_k` → **HTTP 400**
   (`"temperature is deprecated for this model"`) on Sonnet 5 / Opus 5 / Claude 4.7+. Do NOT
   send them; steer tone via the prompt. (Our `llm.py` used to send `temperature` on every
   call — removed in CLAUDE-P0.)
2. **Prefill is gone** (400 on 4.6+) — use structured outputs or explicit instructions.
3. **`thinking.budget_tokens` is gone** — models use **adaptive thinking**
   (`thinking:{type:"adaptive"}`, on by default on Sonnet 5/Opus 5) with depth controlled by
   **`output_config:{effort: low|medium|high|xhigh|max}`** (default `high`).
   - Verified: `effort:"low"` is accepted on `anthropic-version: 2023-06-01` and **suppresses
     the thinking block entirely** → the loop gets clean JSON only, ~half the output tokens.
     We run the loop at `effort:"low"`.
   - ⚠️ Adaptive thinking counts toward `max_tokens`. With a big system prompt, a low
     `max_tokens` could truncate the action before it's emitted — we keep `max_tokens` ≥ 2048
     as insurance (and `effort:"low"` removes thinking anyway).
4. **New tokenizer (~+30% tokens)** on 4.7+ — revisit any `max_tokens` tuned on older models.

## Prompt caching (our biggest cost/latency lever)

Our `system_prompt()` (SOUL + protocol + tool list + handbook index, **~3,000 tokens**) is
**byte-identical on every step of every run, across all brands** — the ideal cache prefix.
The variable tail (GOAL, recalled memory, transcript) lives in the *user* message, so it
doesn't disturb the prefix.

- Syntax (GA, **no beta header** — works on `2023-06-01`; verified accepted):
  ```json
  "system": [{"type": "text", "text": "<SOUL + tools>", "cache_control": {"type": "ephemeral"}}]
  ```
- **Min cacheable tokens is model-dependent:** Sonnet 5 = **1,024** (our ~3k prefix caches);
  Haiku 4.5 = **4,096** (our prefix is *under* the floor → would silently not cache). This is
  why caching only pays once the loop runs on Sonnet 5.
- **Multipliers vs base input:** 5-min write **1.25×**, 1-hour write **2×**, cache read
  **0.1×**. Pays off after **one** read (5m) or two (1h). TTL: `"ttl":"5m"` (default, no
  header) or `"ttl":"1h"` (verify whether the extended-TTL beta header is required first).
- **Verify it's live:** watch `usage.cache_read_input_tokens > 0` on step 2+. `pricing.py`
  already prices cache read/write, so COST-METER stays accurate.
- **Order:** cache resolves `tools → system → messages`; put the biggest/most-stable content
  first. When we adopt native tools, add a second `cache_control` breakpoint on the last tool
  definition (today the tools are text inside the system block, so one breakpoint covers them).
- **Invalidation:** the prefix changes only on a deploy that edits SOUL/tools/handbooks → one
  cold call after each deploy, warm after. Context-editing (`clear_tool_uses`) invalidates the
  cache *after the clear point*; the system prefix stays cached.

## Native tool use (NOT yet adopted — the biggest pending upgrade)

We currently do **JSON-in-text ReAct** (`runner.py` regexes a `{…}` action out of the model's
text). Anthropic's native tool use is more reliable and is the recommended path:
`tools` (with `input_schema`; `strict:true` guarantees schema-valid inputs) → assistant
`tool_use` block (`stop_reason:"tool_use"`) → return a `tool_result` block (must be **first**
in the next user turn, immediately after the `tool_use`) → loop until
`stop_reason != "tool_use"`. Parallel tool calls are default-on (return **all** `tool_result`s
in one user message). Force/disable via `tool_choice` (`auto`/`any`/`tool`/`none`). Tool
schemas cost a per-model system-prompt overhead (~354 tok on Sonnet 5). Structured outputs =
`output_config:{format:{type:"json_schema",schema:{…}}}` (the old `output_format` param is
removed; **incompatible with citations**). `token-efficient-tools` is **retired** — don't build
on it. → tracked as the future **CLAUDE-TOOLS** lane.

## Built-in server tools (worth adopting later)

- **web_search** (`web_search_20260209`+) — $10 / 1,000 searches; real-time facts for replies.
- **web_fetch** (`web_fetch_20260318`) — **free**; summarize a URL already in the conversation.
- **code_execution** (`code_execution_20260521`) — Python sandbox; **free when bundled with
  web_search/web_fetch**; data crunching / charts.
- **memory tool** (`memory_20250818`) — persistent agent memory; **overlaps our Supabase
  `agent_memory`**, so it's a decision, not a freebie.
- Skip bash / text-editor / computer-use unless we add filesystem/GUI automation.
- Server-tool errors return **HTTP 200** with an error object (never raise); web_search/fetch
  results carry `encrypted_content` that must be echoed back verbatim on later turns or the
  request 400s.

## Working with files (for brand PDFs / creatives)

- **Files API** (GA, no beta header): upload once → reference by `file_id` across calls:
  `{"type":"document","source":{"type":"file","file_id":"file_…"}}` (PDF/text) or
  `{"type":"image","source":{"type":"file","file_id":"file_…"}}`. Cache the document block for
  repeat analysis. **PDFs**: 32MB/request, ≤600 pages, vision+text.
- ⚠️ **Files are workspace-scoped, NOT tenant-scoped.** In this multi-brand repo, **never let
  a `file_id` cross brands** — keep our own brand→file_id map server-side.
- **Citations** (`"citations":{"enabled":true}` on document blocks) ground copy claims in a
  source doc — but are **mutually exclusive with structured outputs** (400 if combined).

## Context management (long runs)

- **1M context** is default on Sonnet 5 (no header). Everything counts toward it (system +
  messages + tool results + output + thinking); caching changes cost, not occupancy.
- **Context editing** (beta `context-management-2025-06-27`): `context_management.edits` with
  `clear_tool_uses_20250919` (keep N recent tool results, trigger on input-token threshold)
  bounds tool-result growth — the fix for long runs. Server-side **compaction**
  (`compact-2026-01-12`) is Anthropic's primary long-run strategy. Clearing invalidates the
  cache after the clear point.
- **Long-context prompting:** put large documents/data **near the top**, instruction/query
  last (up to ~30% quality gain); wrap docs in `<document>` XML.

## Keys & config

- `ANTHROPIC_API_KEY` — an **inference** key (`sk-ant-api…`). An admin key (`sk-ant-admin…`)
  cannot call `/v1/messages` (`llm.py` guards against this).
- `AGENT_LLM_MODEL` (default `claude-sonnet-5`), `AGENT_LLM_BASE`, `AGENT_LLM_EFFORT`
  (default `low`).
- `COST_ANTHROPIC_PRICES` — JSON `{model: {input, output, cache_read, cache_write}}` per 1M
  tokens; overrides the `pricing.py` defaults.

## Deferred (with rationale)

- **Streaming** — genuinely low-value for us right now: the loop and content pipeline emit
  small outputs (JSON actions, captions), and streaming matters mainly for large (128K)
  outputs. Revisit if we adopt long-form generation.
- **Native tool use** (CLAUDE-TOOLS) and **built-in server tools** — sequenced after the
  Sonnet 5 move + hardening.
