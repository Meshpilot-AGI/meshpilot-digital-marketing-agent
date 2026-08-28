"""Persona-consistent asset generation — THIN ADAPTER over meshpilot_creative.

The actual engines (MuAPI + HeyGen Video Agent) and the routing live in
the canonical `meshpilot_creative` package now (the one creative pipeline
for Mesh Pilot). This module keeps the public `generate_asset(row, ...)`
signature so the influencer pipeline orchestrator stays unchanged.

  influencer.generate_asset(row, persona=…)        # what callers see
    -> persona_adapter.spec_from_row(persona, row, brand)
    -> meshpilot_creative.generate(spec)
    -> Asset (url, kind, engine, ...)

Stage 2 of docs/plans/2026-06-05-meshpilot-creative-consolidation.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from glitch_signal.influencer.persona import Persona, load_persona

log = structlog.get_logger(__name__)

# `meshpilot_creative` is the shared creative pipeline from the original
# Mesh Pilot monorepo and is NOT bundled in this standalone service. The
# influencer persona-asset engine is the only consumer, so we import it
# lazily: importing this module never fails, and only calling
# `generate_asset()` without the package raises a clear, actionable error.
_CREATIVE_IMPORT_ERROR = (
    "The influencer persona-asset engine requires the `meshpilot_creative` "
    "package, which is not bundled in this standalone service. Install/vendor "
    "it, or use the core content pipeline instead of the influencer engine."
)


def _load_creative():
    try:
        from meshpilot_creative import generate as _creative_generate
        from meshpilot_creative.persona_adapter import _featured_dog, spec_from_row
    except ModuleNotFoundError as exc:  # pragma: no cover - bundled-only path
        raise RuntimeError(_CREATIVE_IMPORT_ERROR) from exc
    return _creative_generate, spec_from_row, _featured_dog


@dataclass(slots=True)
class GenerationResult:
    """Back-compat shape for pipeline.posting_tick + callers."""
    asset_url: str
    model: str
    kind: str               # still | video
    featured_dog: bool
    prompt: str
    reference_count: int
    video_pending: bool = False
    video_error: str | None = None


async def generate_asset(
    row: dict[str, Any],
    *,
    persona: Persona | None = None,
    brand_id: str = "ayurpet",
    **_unused,  # tolerate legacy still_model/video_model kwargs from older callers
) -> GenerationResult:
    """Render the asset for a content-plan row via meshpilot_creative."""
    _creative_generate, spec_from_row, _featured_dog = _load_creative()
    persona = persona or load_persona(row["persona_id"])
    # Persona's brand is authoritative when present; the kwarg is a fallback.
    brand_id = getattr(persona, "brand_id", None) or brand_id
    spec = spec_from_row(persona, row, brand_id)
    asset = await _creative_generate(spec)
    # Decide featured_dog from the same heuristic the spec builder used,
    # so the pipeline note stays informative.
    return GenerationResult(
        asset_url=asset.url,
        model=asset.engine,
        kind=asset.kind,
        featured_dog=_featured_dog(persona, row),
        prompt=asset.prompt,
        reference_count=len(spec.reference_images),
    )
