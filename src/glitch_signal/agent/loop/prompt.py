"""Prompt construction for the agent loop (native tool use).

The system prompt is identity + operating rules + the handbook index — the tools themselves
are passed via the API `tools` param, not listed here. `build_prompt` is the first user turn.
"""
from __future__ import annotations

import functools
import pathlib

_SOUL_PATH = pathlib.Path(__file__).resolve().parents[1] / "SOUL.md"


@functools.lru_cache(maxsize=1)
def _soul() -> str:
    """The agent's durable identity/mission/scope (agent/SOUL.md), prepended to every system prompt."""
    try:
        return _SOUL_PATH.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — never let a missing soul break the loop
        return "You are an autonomous digital-marketing agent working for ONE brand."


SYSTEM = """You are operating as an autonomous agent. Work toward the GOAL using the available
tools, one step at a time: call a tool, read its result, then decide the next step. When you are
finished, reply with your final answer as plain text (no tool call).

Operating rules:
- Call `recall` early to load what you already know about the brand; `remember` any important new
  fact, and always `remember` a short episode of what you did before you finish.
- Do NOT repeat a tool call you already made with the same input — act on the result you got.
  Once a tool gives you what you need, move on; re-calling it wastes your limited steps.
- Before finalizing ANY content (caption, post, blog, etc.), run it through `polish_copy` and use
  the returned clean text.
- Publishing/posting is currently DISABLED; never attempt to publish — plan and generate only."""


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


def system_prompt() -> str:
    # Identity first (who you are + mission + scope + guardrails), then the operating rules, then
    # the handbook index so the agent reads the right playbook without a list round-trip.
    return _soul() + "\n\n---\n\n" + SYSTEM + _playbook_index()


def build_prompt(goal: str, seed_context: str) -> str:
    """The first user turn: the goal + whatever was pre-recalled from memory."""
    return (f"GOAL: {goal}\n\n"
            f"What you already recalled from memory:\n{seed_context or '[]'}")
