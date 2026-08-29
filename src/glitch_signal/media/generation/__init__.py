"""Vendor-pluggable media generation (MEDIA-1).

A deterministic runner executes a **recipe** (a structured plan distilled from a
bundled `muapi-*` SKILL.md) against a **pluggable engine** (MUapi first; fal /
HeyGen slot in behind the same `Engine` protocol later), and returns an `Asset`.

Public surface:
    from glitch_signal.media.generation import generate, get_recipe, list_recipes

See docs/plans/2026-08-29-media-generation.md.
"""
from __future__ import annotations

from glitch_signal.media.generation.compose import llm_compose
from glitch_signal.media.generation.registry import (
    get_recipe,
    list_recipes,
    recipe_for_trigger,
)
from glitch_signal.media.generation.runner import generate, run_recipe
from glitch_signal.media.generation.spec import Asset, Brief

__all__ = [
    "Asset",
    "Brief",
    "generate",
    "run_recipe",
    "get_recipe",
    "list_recipes",
    "recipe_for_trigger",
    "llm_compose",
]
