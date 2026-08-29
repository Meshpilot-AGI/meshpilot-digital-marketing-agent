"""AGENT-LOOP — the memory-backed ReAct agent loop (brain increment 2).

    from glitch_signal.agent.loop import run
"""
from __future__ import annotations

from glitch_signal.agent.loop.runner import parse_action, run

__all__ = ["run", "parse_action"]
