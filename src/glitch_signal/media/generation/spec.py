"""Transport shapes for media generation — small and engine-agnostic.

`Brief` is what a caller wants generated; `Asset` is what the runner returns.
Adapted from the bible's `meshpilot_creative.spec` (CreativeSpec/Asset), trimmed
to what MEDIA-1 needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["image", "video"]


@dataclass(slots=True)
class Brief:
    """A request to run a recipe.

    `inputs` fills the recipe's declared inputs (and any `{{placeholder}}` the
    recipe's phases reference). `brand_id` scopes brand *style* (voice, palette,
    reference images) — brand style flows through the brief, not through a key
    (MUAPI_API_KEY is global infra). Unknown inputs are ignored by the runner;
    missing required inputs raise before any network call.
    """

    brand_id: str
    recipe: str  # recipe slug, e.g. "muapi-product-video-ad-maker"
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Asset:
    """What the runner returns — a finished, hosted asset."""

    url: str
    kind: Kind
    engine: str  # "muapi:<model>"
    recipe: str = ""
    prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
