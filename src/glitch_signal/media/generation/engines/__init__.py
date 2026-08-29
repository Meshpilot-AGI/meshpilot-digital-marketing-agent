"""Pluggable generation engines. MUapi first; fal / HeyGen behind the same
`Engine` protocol later."""
from __future__ import annotations

from glitch_signal.media.generation.engines.base import Engine, EngineError
from glitch_signal.media.generation.engines.muapi import MuapiEngine

__all__ = ["Engine", "EngineError", "MuapiEngine"]
