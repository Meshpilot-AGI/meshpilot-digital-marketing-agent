"""Deterministic recipe runner.

`run_recipe` fills a recipe's `{{placeholders}}` from the brief, executes each
phase in order (a phase's output becomes a `{{var}}` the next phase can use), and
returns the final `Asset`. Engine calls are the only I/O; inject a fake engine to
unit-test with no network.

Template-prompt phases need no LLM. Phases whose prompt is authored by an LLM
(`prompt_mode: "llm"`, or an `op: "llm"` step) call the injected `compose`
callback — so a fully-templated recipe (e.g. product-video-ad-maker) runs with
`compose=None`, while richer recipes get an LLM composer wired in.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from glitch_signal.media.generation.engines.base import Engine, EngineError
from glitch_signal.media.generation.engines.muapi import MuapiEngine
from glitch_signal.media.generation.loader import Recipe
from glitch_signal.media.generation.registry import get_recipe
from glitch_signal.media.generation.spec import Asset, Brief

# (instruction, context_vars) -> authored text
Compose = Callable[[str, dict[str, Any]], Awaitable[str]]

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _render(template: str, variables: dict[str, Any]) -> str:
    """Substitute {{name}} from variables; leave unknown names blank."""
    return _PLACEHOLDER.sub(
        lambda m: str(variables.get(m.group(1), "") or ""), template or ""
    )


def _render_params(params: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    """Render {{placeholders}} inside string param values (e.g. aspect_ratio)."""
    out: dict[str, Any] = {}
    for key, val in params.items():
        if isinstance(val, str):
            out[key] = _render(val, variables)
        elif isinstance(val, list):
            out[key] = [_render(x, variables) if isinstance(x, str) else x for x in val]
        else:
            out[key] = val
    return out


def _resolve_inputs(recipe: Recipe, given: dict[str, Any]) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    missing: list[str] = []
    for spec in recipe.inputs:
        val = given.get(spec.name)
        if val not in (None, ""):
            variables[spec.name] = val
        elif spec.default is not None:
            variables[spec.name] = spec.default
        elif spec.required:
            missing.append(spec.name)
    if missing:
        raise EngineError(f"{recipe.slug}: missing required input(s): {', '.join(missing)}")
    # carry any extra placeholders the caller supplied (not declared as inputs)
    for key, val in given.items():
        variables.setdefault(key, val)
    return variables


async def run_recipe(
    recipe: Recipe,
    inputs: dict[str, Any],
    *,
    engine: Engine,
    compose: Compose | None = None,
    timeout_s: int = 360,
) -> Asset:
    variables = _resolve_inputs(recipe, inputs)
    prompt_by_output: dict[str, str] = {}
    model_by_output: dict[str, str] = {}

    async def _author(instruction: str) -> str:
        if compose is None:
            raise EngineError(
                f"{recipe.slug}: an LLM composer is required (a phase authors its "
                f"prompt) but none was provided"
            )
        return await compose(instruction, dict(variables))

    for phase in recipe.phases:
        if phase.op == "llm":
            variables[phase.output] = await _author(_render(phase.prompt, variables))
            continue

        if phase.prompt_mode == "llm":
            prompt = await _author(_render(phase.prompt, variables))
        else:
            prompt = _render(phase.prompt, variables)

        images = [img for img in (_render(i, variables) for i in phase.images) if img]
        if phase.op in {"image.edit", "video.from_image"} and not images:
            raise EngineError(f"{recipe.slug}: phase {phase.id!r} resolved to no reference image")

        url = await engine.generate(
            phase.model,  # type: ignore[arg-type]  (loader guarantees engine phases have a model)
            prompt,
            images=images,
            params=_render_params(phase.params, variables),
            timeout_s=timeout_s,
        )
        variables[phase.output] = url
        prompt_by_output[phase.output] = prompt
        model_by_output[phase.output] = phase.model  # type: ignore[assignment]

    final_url = variables.get(recipe.returns)
    if not final_url:
        raise EngineError(f"{recipe.slug}: no output produced for returns={recipe.returns!r}")

    model = model_by_output.get(recipe.returns, "")
    return Asset(
        url=str(final_url),
        kind=recipe.kind,  # type: ignore[arg-type]
        engine=f"{engine.name}:{model}" if model else engine.name,
        recipe=recipe.slug,
        prompt=prompt_by_output.get(recipe.returns, ""),
        metadata={"phases": [p.id for p in recipe.phases]},
    )


async def generate(
    brief: Brief,
    *,
    engine: Engine | str | None = None,
    compose: Compose | None = None,
    timeout_s: int = 360,
) -> Asset:
    """Convenience: resolve the recipe by slug and run it. `engine` may be an Engine instance,
    a name ('muapi' | 'heygen'), or None (defaults to MUapi)."""
    from glitch_signal.media.generation.engines import get_engine

    recipe = get_recipe(brief.recipe)
    if engine is None:
        engine = recipe.engine        # recipe declares its vendor (default "muapi")
    if isinstance(engine, str):
        engine = get_engine(engine)
    return await run_recipe(
        recipe,
        brief.inputs,
        engine=engine,
        compose=compose,
        timeout_s=timeout_s,
    )
