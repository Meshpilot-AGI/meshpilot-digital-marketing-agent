"""Recipe registry — loads the bundled recipe library once and looks recipes up
by slug or trigger keyword."""
from __future__ import annotations

from functools import lru_cache

from glitch_signal.media.generation.loader import Recipe, load_all


@lru_cache(maxsize=1)
def _recipes() -> dict[str, Recipe]:
    return load_all()


def list_recipes() -> list[Recipe]:
    return list(_recipes().values())


def get_recipe(slug: str) -> Recipe:
    r = _recipes().get(slug)
    if r is None:
        raise KeyError(f"unknown recipe {slug!r}; known: {sorted(_recipes())}")
    return r


def recipe_for_trigger(text: str) -> Recipe | None:
    """First recipe whose trigger keyword is a substring of `text` (longest
    trigger wins, so a specific match beats a generic one)."""
    t = (text or "").lower()
    best: tuple[int, Recipe] | None = None
    for r in _recipes().values():
        for kw in r.triggers:
            if kw and kw.lower() in t and (best is None or len(kw) > best[0]):
                best = (len(kw), r)
    return best[1] if best else None
