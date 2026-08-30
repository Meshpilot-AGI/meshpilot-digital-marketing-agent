"""The agent loop (AGENT-LOOP) — recall → plan → act → observe → repeat → episode.

A native tool-use loop over Claude: each turn the model returns tool_use block(s) or finishes
with plain text; the loop runs each tool_use through the policy gate and returns tool_result
block(s), until the model stops calling tools (`stop_reason != "tool_use"`). Every run writes an
episode to memory. Publishing is denied by `policy.allow`, so the agent can plan/generate/
remember but cannot post.

`llm` and `execute` are injectable so the loop unit-tests with a scripted model + fake tools.
The injected `llm` has the `complete_tools` shape: async (messages, *, tools, system) ->
{content, stop_reason, usage}.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import structlog

from glitch_signal.agent.loop import policy, tools
from glitch_signal.agent.loop import llm as agent_llm
from glitch_signal.agent.loop.prompt import build_prompt, system_prompt

log = structlog.get_logger(__name__)

LLMFn = Callable[..., Awaitable[dict]]
ExecFn = Callable[[str, dict, str], Awaitable[str]]


def _final_text(content: list[dict]) -> str:
    """Join the assistant's text blocks — the final answer when it stops calling tools."""
    return "".join(b.get("text", "") for b in content
                   if isinstance(b, dict) and b.get("type") == "text").strip()


async def _write_episode(brand_id: str, goal: str, transcript: list[dict], final: str,
                         execute: ExecFn) -> None:
    actions = [t.get("action") for t in transcript if t.get("action")]
    content = f"Goal: {goal}. Actions: {', '.join(actions) or 'none'}. Result: {final}"
    try:
        await execute("remember", {"kind": "episode", "content": content[:2000]}, brand_id)
    except Exception as exc:  # noqa: BLE001 — episode logging must never fail the run
        log.warning("agent.loop.episode_write_failed", error=str(exc)[:200])


async def run(
    brand_id: str,
    goal: str,
    *,
    llm: LLMFn | None = None,
    execute: ExecFn | None = None,
    mcp: Any = None,
    max_steps: int = 8,
) -> dict[str, Any]:
    """Run the loop for a goal. Returns {final, transcript, steps}.

    When `execute` is not injected (production), the brand's configured MCP servers are connected,
    their tools discovered and offered to the LLM (namespaced `mcp__server__tool`), and calls to
    them routed through the same policy gate. `mcp` (an entered MCPManager) can be injected for tests.
    """
    from glitch_signal.analytics.cost import budget as cost_budget
    from glitch_signal.analytics.cost import set_brand
    set_brand(brand_id)  # attribute every vendor call in this run to the brand (COST-METER)

    max_steps = cost_budget.clamp_steps(max_steps)  # INC-3: hard ceiling (fixes unbounded max_steps)

    # INC-3: on the production path, halt before spending if the brand is over its daily budget.
    if execute is None:
        allowed, reason = await cost_budget.check(brand_id)
        if not allowed:
            return {"final": f"halted: {reason}", "transcript": [], "steps": 0, "denied": "budget"}

    llm = llm or agent_llm.complete_tools
    base_execute = execute or tools.execute

    # Connect MCP only on the production path (execute not injected) and only if not already given.
    own_mcp = False
    if mcp is None and execute is None:
        from glitch_signal.agent.mcp import manager_for_brand
        mcp = await manager_for_brand(brand_id)
        await mcp.__aenter__()
        own_mcp = True

    tool_defs = tools.tool_defs() + (mcp.tool_defs() if mcp is not None else [])
    sys = system_prompt()

    async def dispatch(tool_name: str, args: dict, bid: str) -> str:
        if mcp is not None and mcp.has(tool_name):
            return await mcp.call(tool_name, args)
        return await base_execute(tool_name, args, bid)

    try:
        seed = await base_execute("recall", {"query": goal, "k": 5}, brand_id)
        transcript: list[dict] = []
        counts: dict[str, int] = {}  # executed tool counts this run — feeds per-run budgets
        messages: list[dict] = [{"role": "user", "content": build_prompt(goal, seed)}]

        for step in range(max_steps):
            resp = await llm(messages, tools=tool_defs, system=sys)
            content = resp.get("content", []) or []
            messages.append({"role": "assistant", "content": content})
            tool_uses = [b for b in content
                         if isinstance(b, dict) and b.get("type") == "tool_use"]

            if resp.get("stop_reason") != "tool_use" or not tool_uses:
                final = _final_text(content)
                await _write_episode(brand_id, goal, transcript, final, base_execute)
                return {"final": final, "transcript": transcript, "steps": step + 1}

            results: list[dict] = []
            for b in tool_uses:
                name = str(b.get("name", ""))
                args = b.get("input", {}) or {}
                allowed, reason = policy.allow(name, args, brand_id, counts=counts)
                if allowed:
                    obs = await dispatch(name, args, brand_id)
                    counts[name] = counts.get(name, 0) + 1  # only count what actually ran
                else:
                    obs = f"DENIED: {reason}"
                results.append({"type": "tool_result", "tool_use_id": b.get("id"),
                                "content": obs, "is_error": (not allowed) or obs.startswith("ERROR")})
                transcript.append({"action": name, "args": args, "observation": obs})
            messages.append({"role": "user", "content": results})

        await _write_episode(brand_id, goal, transcript, "(max steps reached)", base_execute)
        return {"final": None, "transcript": transcript, "steps": max_steps}
    finally:
        if own_mcp:
            await mcp.__aexit__(None, None, None)
