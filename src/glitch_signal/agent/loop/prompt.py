"""ReAct prompt construction for the agent loop."""
from __future__ import annotations

import json

from glitch_signal.agent.loop.tools import tool_descriptions

SYSTEM = """You are an autonomous social-media marketing agent working for ONE brand.
Accomplish the GOAL by thinking step by step and using TOOLS. Available tools:
{tools}

Respond with a SINGLE JSON object and NOTHING else — either use a tool:
  {{"thought": "<brief reasoning>", "action": "<tool_name>", "args": {{...}}}}
or finish:
  {{"thought": "<brief reasoning>", "final": "<summary of what you did / the answer>"}}

Rules:
- Call `recall` early to load what you already know about the brand; `remember` any
  important new fact, and always `remember` a short episode of what you did before finishing.
- Publishing/posting is currently DISABLED — never attempt to publish; plan and generate only.
- Output ONLY the JSON object. No markdown fences, no prose outside the JSON."""


def system_prompt() -> str:
    return SYSTEM.format(tools=tool_descriptions())


def build_prompt(goal: str, seed_context: str, transcript: list[dict]) -> str:
    lines = [f"GOAL: {goal}", "", "What you already recalled from memory:", seed_context or "[]", ""]
    if transcript:
        lines.append("Steps so far:")
        for i, t in enumerate(transcript, 1):
            if "error" in t:
                lines.append(f"{i}. (unparseable response — respond with valid JSON)")
                continue
            lines.append(
                f"{i}. action={t.get('action')} args={json.dumps(t.get('args', {}))} "
                f"-> observation: {str(t.get('observation'))[:400]}"
            )
        lines.append("")
    lines.append("Your next JSON action:")
    return "\n".join(lines)
