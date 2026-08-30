# CLAUDE-TOOLS — native tool use for the agent loop

**Status:** design (awaiting build)  ·  **Opened:** 2026-08-30  ·  **Owner:** Claude
**Follows:** CLAUDE-PLATFORM (Sonnet 5 + hardening). See `docs/vendors/anthropic.md` §"Native tool use".

## Why

The loop is a **JSON-in-text ReAct**: `runner.py` lists tools as prose, the model returns a
JSON blob, `parse_action` (`re.search(r"\{.*\}")`) extracts it, the policy gate runs, execute,
feed the observation back as text, repeat. Problems: brittle regex parsing (a stray brace or
prose breaks a step), no schema validation of tool inputs, no parallel tool calls, and the
model must be told the JSON protocol in the system prompt. Anthropic's **native tool use** is
the recommended path and fixes all four.

## Target design

### 1. Tool schemas (`agent/loop/tools.py`)
Each `TOOLS[name]` gains an `input_schema` (JSON Schema, `additionalProperties:false`, `required`
set) so we can pass `strict: true`. New `tool_defs()` → `[{name, description, input_schema}]`
for the API `tools` param; `tool_descriptions()` (prose) is removed. `execute()` is unchanged.

Example:
```python
"recall": {"fn": _t_recall, "description": "Search the brand's memory.",
           "input_schema": {"type": "object", "additionalProperties": False,
                            "properties": {"query": {"type": "string"},
                                           "k": {"type": "integer", "default": 5}},
                            "required": ["query"]}}
```

### 2. Transport (`agent/loop/llm.py`)
New `complete_tools(messages, *, tools, system, model, max_tokens, effort, client) -> dict`
returns the **full assistant message** (`{role, content:[…blocks], stop_reason}`), not just
text. Keeps our thin httpx transport, `_meter`, retry/Retry-After, and prompt caching — plus a
**second `cache_control` breakpoint on the last tool definition** (tools cache separately, ahead
of system). We do **not** adopt the Anthropic SDK / Tool Runner (it would bypass `_meter` and our
injectable test seams). `complete()`/`complete_messages()` stay for the content pipeline.

### 3. Loop (`agent/loop/runner.py`)
Rewrite to the native cycle:
```
messages = [ {user: goal + seed recall} ]
loop (≤ max_steps):
    resp = complete_tools(messages, tools=tool_defs()+mcp_defs, system=SYSTEM)
    append resp (assistant) to messages
    if resp.stop_reason != "tool_use":            # end_turn → done
        final = text(resp); write episode; return final
    results = []
    for block in resp.tool_use_blocks:            # parallel-safe
        allowed, reason = policy.allow(block.name, block.input, brand, counts)
        obs = dispatch(block.name, block.input) if allowed else f"DENIED: {reason}"
        results.append(tool_result(block.id, obs, is_error=not allowed or obs.startswith("ERROR")))
    append {user: results} to messages
```
- **Final answer** = the assistant's `end_turn` text (the `{final}` JSON convention is dropped).
- `recall` is seeded as the first turn's context (as today) or left to the model; `remember`
  episode-write on finish stays.
- `parse_action` is deleted.

### 4. Policy gate (`agent/loop/policy.py`)
Signature unchanged. Each `tool_use` block is gated before dispatch; a denial becomes a
`tool_result` with `is_error:true` carrying the reason, so the model can adapt.

### 5. MCP tools (`agent/mcp/client.py`)
`list_tools()` already returns each tool's `inputSchema` but the manager discards it
(`_tools[ns] = (server, tool, description)`). Capture it → `(_tools[ns] = (server, tool,
description, input_schema)`), add `tool_defs()` returning namespaced native tool defs, and keep
`call(namespaced, args)`. The loop concatenates built-in `tool_defs()` + `mcp.tool_defs()`.

### 6. System prompt (`agent/loop/prompt.py`)
Drop the "respond with a SINGLE JSON object" protocol block (native tools replace it). Keep
SOUL + the operating rules (recall early; `polish_copy` before finalizing; publishing disabled;
don't repeat a tool call with the same input) + the handbook index. `build_prompt` becomes the
first user message (goal + seed recall); subsequent turns are native tool_result messages.

### 7. Tests
`test_agent_loop.py`: the injectable `llm` seam now returns structured responses (assistant
messages with `tool_use` blocks) instead of a JSON string; scripted multi-step runs assert the
`tool_use → tool_result → end_turn` cycle, parallel tool handling, and a denied tool producing an
`is_error` result. `test_llm_messages.py`: `complete_tools` payload shape (tools param, both cache
breakpoints, `strict`).

## Verification
- Unit: full suite green.
- **Live (real Sonnet 5)**: a native `tool_use` round-trip — model calls `recall`, we return a
  `tool_result`, model finishes with `end_turn` text. Confirm `stop_reason` transitions and that
  `strict` schemas reject a malformed input.
- **Prod**: a real Discord `#agent-chat` run returns a coherent answer; cost meter shows the
  tool-use system-prompt overhead (~354 tok on Sonnet 5) + cache reads.

## Risks / mitigations
- **Loop rewrite is the core** — keep the injectable `llm`/`execute` seams so it stays unit-testable;
  land behind the same `max_steps` clamp + budget check.
- **Thinking + tool use** — adaptive thinking blocks must be preserved verbatim in the assistant
  message we send back (with tool_use). Keep `effort` configurable; the tool loop may warrant
  `medium`. Verify the thinking-block round-trip live.
- **MCP schema variance** — some servers return loose schemas; pass them through as-is (don't set
  `strict` on MCP tools), `strict:true` only on our own built-ins.
- **`is_error` semantics** — our tools return `"ERROR: …"` strings today; map those to
  `is_error:true` so the model self-corrects.

## Out of scope (later lanes)
Built-in server tools (web_search/web_fetch/code_execution), Files API, context editing,
structured-output `output_config.format`. Streaming stays deferred.

## Write-back
`docs/vendors/anthropic.md` (flip "native tool use — NOT yet adopted" → adopted),
`control-plane/ACTIVE_LANE_BOARD.md`, `control-plane/ENGINEERING_SUPERVISOR.md`.
