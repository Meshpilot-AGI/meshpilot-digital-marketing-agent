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

from glitch_signal.agent.loop import conscience, policy, reckoning, scopes, tools
from glitch_signal.agent.loop import llm as agent_llm
from glitch_signal.agent.loop.prompt import build_prompt, system_prompt

log = structlog.get_logger(__name__)

LLMFn = Callable[..., Awaitable[dict]]
ExecFn = Callable[[str, dict, str], Awaitable[str]]


def _final_text(content: list[dict]) -> str:
    """Join the assistant's text blocks — the final answer when it stops calling tools."""
    return "".join(b.get("text", "") for b in content
                   if isinstance(b, dict) and b.get("type") == "text").strip()


def _deliberation_summary(deliberation: dict) -> str:
    """Compact one-line-ish tail folded into the episode so LEARN can curate self-flagged patterns."""
    out = ""
    r = deliberation.get("reckoning") or {}
    c = deliberation.get("conscience") or {}
    if r:
        out += f" | Reckoning[{r.get('trust')}]: met={r.get('met')}"
        if r.get("discrepancy"):
            out += f"; {r['discrepancy']}"
        if r.get("attribution") not in (None, "none"):
            out += f"; cause={r['attribution']}"
        if r.get("lesson"):
            out += f"; lesson={r['lesson']}"
    if c:
        out += f" | Conscience: {c.get('verdict')}"
        if c.get("notes"):
            out += f"; {c['notes']}"
    return out


async def _write_episode(brand_id: str, goal: str, transcript: list[dict], final: str,
                         execute: ExecFn, *, deliberation: dict | None = None) -> None:
    actions = [t.get("action") for t in transcript if t.get("action")]
    content = f"Goal: {goal}. Actions: {', '.join(actions) or 'none'}. Result: {final}"
    if deliberation:
        content += _deliberation_summary(deliberation)
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
    scope: str = scopes.DEFAULT_SCOPE,
) -> dict[str, Any]:
    """Run the loop for a goal. Returns {final, transcript, steps}.

    When `execute` is not injected (production), the brand's configured MCP servers are connected,
    their tools discovered and offered to the LLM (namespaced `mcp__server__tool`), and calls to
    them routed through the same policy gate. `mcp` (an entered MCPManager) can be injected for tests.
    """
    from glitch_signal.analytics.cost import budget as cost_budget
    from glitch_signal.analytics.cost import set_brand
    set_brand(brand_id)  # attribute every vendor call in this run to the brand (COST-METER)
    scopes.set_current(scope)  # SCOPE: bound this run's toolset; the schedule tool clamps to ⊆ this

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

    # Built-in client tools + Anthropic server tools (web_search/web_fetch) + this brand's MCP tools,
    # then SCOPE-filtered: the model is only offered the tools the active scope allows.
    active_scope = scopes.resolve(scope)
    _all_defs = (tools.tool_defs() + tools.server_tool_defs()
                 + (mcp.tool_defs() if mcp is not None else []))
    tool_defs = [d for d in _all_defs if active_scope.allows(d["name"])]
    log.info("agent.loop.scope", scope=active_scope.name, offered=len(tool_defs), total=len(_all_defs))
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

        # DELIBERATION (advisory, flag-gated OFF). Expectation is captured BEFORE acting (foresight,
        # not hindsight); reckoning + conscience run at the single finalize point below.
        from glitch_signal.config import settings as _settings
        _reck_on = bool(getattr(_settings(), "agent_reckoning_enabled", False))
        _consc_on = bool(getattr(_settings(), "agent_conscience_enabled", False))
        expectation_text = await reckoning.expectation(goal, seed) if _reck_on else ""

        async def _finalize(episode_final: str, steps: int, ret_final: Any) -> dict[str, Any]:
            delib: dict[str, Any] = {}
            if _reck_on:
                r = await reckoning.reckon(goal, expectation_text, transcript, episode_final)
                if r:
                    delib["reckoning"] = r
            if _consc_on:
                c = await conscience.review(goal, episode_final)
                if c:
                    delib["conscience"] = c
            if delib:
                log.info("agent.loop.deliberation", brand=brand_id,
                         met=(delib.get("reckoning") or {}).get("met"),
                         verdict=(delib.get("conscience") or {}).get("verdict"))
            await _write_episode(brand_id, goal, transcript, episode_final, base_execute,
                                 deliberation=delib)
            return {"final": ret_final, "transcript": transcript, "steps": steps, **delib}

        for step in range(max_steps):
            resp = await llm(messages, tools=tool_defs, system=sys)
            content = resp.get("content", []) or []
            messages.append({"role": "assistant", "content": content})
            stop = resp.get("stop_reason")

            # A long server-tool turn (web_search/web_fetch) can pause; re-send to resume rather
            # than treating it as the final answer. Bounded by max_steps.
            if stop == "pause_turn":
                continue

            tool_uses = [b for b in content
                         if isinstance(b, dict) and b.get("type") == "tool_use"]

            if stop != "tool_use" or not tool_uses:
                final = _final_text(content)
                return await _finalize(final, step + 1, final)

            results: list[dict] = []
            for b in tool_uses:
                name = str(b.get("name", ""))
                args = b.get("input", {}) or {}
                # SCOPE enforced at DISPATCH, not just at the offer — a crafted/hallucinated
                # tool_use for an out-of-scope tool must not execute even if policy would allow it.
                if not active_scope.allows(name):
                    obs = f"DENIED: tool {name!r} is out of scope ({active_scope.name})"
                else:
                    allowed, reason = policy.allow(name, args, brand_id, counts=counts)
                    if allowed:
                        obs = await dispatch(name, args, brand_id)
                        counts[name] = counts.get(name, 0) + 1  # only count what actually ran
                    else:
                        obs = f"DENIED: {reason}"
                results.append({"type": "tool_result", "tool_use_id": b.get("id"),
                                "content": obs, "is_error": obs.startswith(("DENIED", "ERROR"))})
                transcript.append({"action": name, "args": args, "observation": obs})
            messages.append({"role": "user", "content": results})

        return await _finalize("(max steps reached)", max_steps, None)
    finally:
        if own_mcp:
            await mcp.__aexit__(None, None, None)
