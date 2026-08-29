"""The agent loop (AGENT-LOOP) — recall → plan → act → observe → repeat → episode.

A ReAct loop over a completion model (muapi text): each step the LLM emits a JSON action
(`{action, args}`) or a `{final}`; the loop runs the tool through the policy gate, feeds the
observation back, and continues. Every run writes an episode to memory. Publishing is denied
by `policy.allow`, so the agent can plan/generate/remember but cannot post.

`llm` and `execute` are injectable so the loop unit-tests with a scripted LLM + fake tools.
"""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

import structlog

from glitch_signal.agent.loop import policy, tools
from glitch_signal.agent.loop import llm as agent_llm
from glitch_signal.agent.loop.prompt import build_prompt, system_prompt

log = structlog.get_logger(__name__)

LLMFn = Callable[..., Awaitable[str]]
ExecFn = Callable[[str, dict, str], Awaitable[str]]


def parse_action(raw: str) -> dict | None:
    """Extract the first JSON object from the model output."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


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
    max_steps: int = 8,
) -> dict[str, Any]:
    """Run the loop for a goal. Returns {final, transcript, steps}."""
    llm = llm or agent_llm.complete
    execute = execute or tools.execute
    sys = system_prompt()

    seed = await execute("recall", {"query": goal, "k": 5}, brand_id)
    transcript: list[dict] = []
    counts: dict[str, int] = {}  # executed tool counts this run — feeds per-run budgets

    for step in range(max_steps):
        raw = await llm(build_prompt(goal, seed, transcript), system=sys)
        action = parse_action(raw)
        if action is None:
            transcript.append({"error": "unparseable", "raw": (raw or "")[:300]})
            continue
        if "final" in action:
            final = str(action.get("final", ""))
            await _write_episode(brand_id, goal, transcript, final, execute)
            return {"final": final, "transcript": transcript, "steps": step + 1}

        tool = str(action.get("action", ""))
        args = action.get("args", {}) or {}
        allowed, reason = policy.allow(tool, args, brand_id, counts=counts)
        if allowed:
            obs = await execute(tool, args, brand_id)
            counts[tool] = counts.get(tool, 0) + 1  # only count what actually ran
        else:
            obs = f"DENIED: {reason}"
        transcript.append({
            "thought": action.get("thought"), "action": tool, "args": args, "observation": obs,
        })

    await _write_episode(brand_id, goal, transcript, "(max steps reached)", execute)
    return {"final": None, "transcript": transcript, "steps": max_steps}
