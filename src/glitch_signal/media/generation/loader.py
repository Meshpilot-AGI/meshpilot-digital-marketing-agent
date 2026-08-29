"""Recipe model + loader.

A recipe ships as a directory under `recipe_library/<slug>/`:
  - `SKILL.md`     — the muapi-* skill, bundled verbatim (provenance + the
                     human-readable "skill used at runtime").
  - `recipe.json`  — the structured execution plan distilled from that SKILL.md.

We execute the manifest (robust, deterministic) rather than parsing free-form
markdown at runtime; `tests/test_media_generation.py` guards the two against
drift (every manifest model + template must trace back to its SKILL.md).

Ops:
  image.generate   — text→image           (no reference image required)
  image.edit       — image→image          (>=1 reference image required)
  video.from_image — image→video          (>=1 reference image required)
  llm              — author text (a prompt) from an instruction; no engine call
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RECIPE_DIR = Path(__file__).resolve().parent / "recipe_library"

_IMAGE_OPS = {"image.generate", "image.edit"}
_VIDEO_OPS = {"video.from_image"}
_ENGINE_OPS = _IMAGE_OPS | _VIDEO_OPS
_NEEDS_IMAGE = {"image.edit", "video.from_image"}
VALID_OPS = _ENGINE_OPS | {"llm"}


class RecipeError(ValueError):
    """A malformed recipe manifest."""


@dataclass(frozen=True, slots=True)
class InputSpec:
    name: str
    type: str = "text"
    required: bool = False
    default: Any = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class Phase:
    id: str
    op: str
    output: str  # variable name this phase binds (its produced url / text)
    model: str | None = None
    prompt_mode: str = "template"  # "template" | "llm"
    prompt: str = ""  # template text, or (llm mode) the authoring instruction
    images: tuple[str, ...] = ()  # placeholder refs, e.g. "{{product}}"
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_engine(self) -> bool:
        return self.op in _ENGINE_OPS

    @property
    def kind(self) -> str:
        return "video" if self.op in _VIDEO_OPS else "image"


@dataclass(frozen=True, slots=True)
class Recipe:
    slug: str
    description: str
    triggers: tuple[str, ...]
    inputs: tuple[InputSpec, ...]
    phases: tuple[Phase, ...]
    returns: str  # the phase output that is the final asset
    skill_md: str = ""

    @property
    def kind(self) -> str:
        """image | video — the kind of the returned asset."""
        by_out = {p.output: p for p in self.phases if p.is_engine}
        final = by_out.get(self.returns)
        return final.kind if final else "image"


def _phase_from(raw: dict[str, Any], slug: str) -> Phase:
    op = raw.get("op", "")
    if op not in VALID_OPS:
        raise RecipeError(f"{slug}: phase {raw.get('id')!r} has invalid op {op!r}")
    images = tuple(raw.get("images", ()) or ())
    prompt_mode = raw.get("prompt_mode", "template")
    if prompt_mode not in {"template", "llm"}:
        raise RecipeError(f"{slug}: phase {raw.get('id')!r} bad prompt_mode {prompt_mode!r}")
    phase = Phase(
        id=str(raw.get("id") or op),
        op=op,
        output=str(raw["output"]),
        model=raw.get("model"),
        prompt_mode=prompt_mode,
        prompt=raw.get("prompt", ""),
        images=images,
        params=dict(raw.get("params", {}) or {}),
    )
    if phase.is_engine and not phase.model:
        raise RecipeError(f"{slug}: engine phase {phase.id!r} needs a model")
    if op in _NEEDS_IMAGE and not images:
        raise RecipeError(f"{slug}: {op} phase {phase.id!r} needs >=1 reference image")
    if not phase.prompt:
        raise RecipeError(f"{slug}: phase {phase.id!r} has no prompt/instruction")
    return phase


def load_recipe(recipe_dir: Path) -> Recipe:
    manifest_path = recipe_dir / "recipe.json"
    if not manifest_path.exists():
        raise RecipeError(f"no recipe.json in {recipe_dir}")
    m = json.loads(manifest_path.read_text())
    phases = tuple(_phase_from(p, m.get("slug", recipe_dir.name)) for p in m.get("phases", []))
    if not phases:
        raise RecipeError(f"{recipe_dir.name}: recipe has no phases")
    returns = m.get("returns") or phases[-1].output
    outputs = {p.output for p in phases}
    if returns not in outputs:
        raise RecipeError(f"{m.get('slug')}: returns {returns!r} not produced by any phase")
    skill = ""
    skill_path = recipe_dir / "SKILL.md"
    if skill_path.exists():
        skill = skill_path.read_text()
    return Recipe(
        slug=str(m.get("slug") or recipe_dir.name),
        description=str(m.get("description", "")),
        triggers=tuple(m.get("triggers", ()) or ()),
        inputs=tuple(
            InputSpec(
                name=i["name"],
                type=i.get("type", "text"),
                required=bool(i.get("required", False)),
                default=i.get("default"),
                description=i.get("description", ""),
            )
            for i in m.get("inputs", [])
        ),
        phases=phases,
        returns=returns,
        skill_md=skill,
    )


def load_all(base: Path = RECIPE_DIR) -> dict[str, Recipe]:
    out: dict[str, Recipe] = {}
    if not base.exists():
        return out
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "recipe.json").exists():
            r = load_recipe(child)
            out[r.slug] = r
    return out
