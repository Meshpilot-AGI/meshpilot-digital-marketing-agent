"""ReAct prompt construction for the agent loop."""
from __future__ import annotations

import functools
import json
import pathlib

from glitch_signal.agent.loop.tools import tool_descriptions

_SOUL_PATH = pathlib.Path(__file__).resolve().parents[1] / "SOUL.md"


@functools.lru_cache(maxsize=1)
def _soul() -> str:
    """The agent's durable identity/mission/scope (agent/SOUL.md), prepended to every system prompt."""
    try:
        return _SOUL_PATH.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — never let a missing soul break the loop
        return "You are an autonomous digital-marketing agent working for ONE brand."


SYSTEM = """Accomplish the GOAL by thinking step by step and using TOOLS. Available tools:
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


def _playbook_index() -> str:
    """The handbook list, always in-prompt so the agent goes straight to `read_playbook` (no
    `list_playbooks` round-trip to loop on)."""
    try:
        from glitch_signal.agent.playbooks import list_playbooks

        pbs = list_playbooks()
        if not pbs:
            return ""
        lines = "\n".join(f"- {p.slug}: {p.description}" for p in pbs)
        return ("\n\nYOUR HANDBOOKS — `read_playbook` the relevant one BEFORE specialized work "
                "(ads audits, per-platform captions/copy, SEO, YouTube, ORM, tracking):\n" + lines)
    except Exception:  # noqa: BLE001
        return ""


def system_prompt(extra_tools: dict[str, str] | None = None) -> str:
    tools = tool_descriptions()
    if extra_tools:
        tools += "\n" + "\n".join(f"- {name}: {desc}" for name, desc in extra_tools.items())
    # Identity first (who you are + mission + scope + guardrails), then the operating protocol,
    # then the handbook index so the agent reads the right playbook without a list round-trip.
    return _soul() + "\n\n---\n\n" + SYSTEM.format(tools=tools) + _playbook_index()


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
