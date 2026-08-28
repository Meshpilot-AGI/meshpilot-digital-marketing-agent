"""Persona loader — mirrors the brand-config pattern.

Live personas live in `brand/personas/<persona_id>.json` (gitignored,
like brand configs); committed templates in `brand/personas.example/`.
Validated against `brand/schema/persona.schema.json`.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

_REPO = pathlib.Path(__file__).resolve().parents[3]  # .../src/social_agent
_PERSONA_DIR = _REPO / "brand" / "personas"
_PERSONA_EXAMPLE_DIR = _REPO / "brand" / "personas.example"
_SCHEMA = _REPO / "brand" / "schema" / "persona.schema.json"


@dataclass(slots=True)
class Persona:
    persona_id: str
    brand_id: str
    display_name: str
    archetype: str
    content_pillars: list[str]
    visual_identity: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def companion(self) -> dict[str, Any] | None:
        return self.raw.get("companion")

    @property
    def languages(self) -> list[str]:
        return self.raw.get("languages") or ["en"]

    @property
    def egress_country(self) -> str | None:
        return (self.raw.get("egress") or {}).get("country")


def _resolve(persona_id: str) -> pathlib.Path:
    live = _PERSONA_DIR / f"{persona_id}.json"
    if live.exists():
        return live
    example = _PERSONA_EXAMPLE_DIR / f"{persona_id}.example.json"
    if example.exists():
        return example
    raise FileNotFoundError(
        f"persona '{persona_id}' not found in {_PERSONA_DIR} or {_PERSONA_EXAMPLE_DIR}"
    )


def load_persona(persona_id: str, *, validate: bool = True) -> Persona:
    path = _resolve(persona_id)
    cfg = json.loads(path.read_text())
    if cfg.get("persona_id") != persona_id:
        raise ValueError(f"persona_id mismatch: file {path.name} declares {cfg.get('persona_id')!r}")
    if validate:
        try:
            import jsonschema  # optional dep
            jsonschema.validate(cfg, json.loads(_SCHEMA.read_text()))
        except ImportError:
            pass  # structural load is enough when jsonschema isn't installed
    return Persona(
        persona_id=cfg["persona_id"],
        brand_id=cfg["brand_id"],
        display_name=cfg["display_name"],
        archetype=cfg["archetype"],
        content_pillars=cfg["content_pillars"],
        visual_identity=cfg["visual_identity"],
        raw=cfg,
    )


def list_personas() -> list[str]:
    ids: set[str] = set()
    for d, suffix in ((_PERSONA_DIR, ".json"), (_PERSONA_EXAMPLE_DIR, ".example.json")):
        if d.exists():
            for f in d.glob(f"*{suffix}"):
                ids.add(f.name[: -len(suffix)])
    return sorted(ids)
