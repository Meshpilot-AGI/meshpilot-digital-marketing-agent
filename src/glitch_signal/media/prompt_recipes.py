"""Prompt-recipe knowledge for the diffusion / generative-video paths
(GROW-SOCIAL-RENDER-3).

Knowledge adapted (NOT copied) from SamurAIGPT/Generative-Media-Skills —
its 41 SKILL.md recipes encode how to prompt image/video models well. We
distill the transferable *technique* into pure prompt-builder functions
our pipeline calls when generating ILLUSTRATIVE / PHOTOREAL / MOTION
content via the MUAPI client.

Division of labour (settled):
- Text-accurate graphics (tables, stat cards, exact numbers) -> design-as-
  code: media/html_render.py. NOT here.
- Illustrative / photoreal stills + short video -> diffusion / gen-video,
  and THOSE prompts are what this module builds well.

Everything here is a pure function (no I/O, no config) so it unit-tests
trivially and composes with muapi.generate_image / muapi.render.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Cinema Director: creative intent → cinematographic directives ──────
# Adapted from the cinema-director recipe's intent-mapping table.
@dataclass(frozen=True)
class ShotDirectives:
    framing: str
    movement: str
    lighting: str


INTENT_MAP: dict[str, ShotDirectives] = {
    "heroic":        ShotDirectives("low-angle wide shot", "slow crane up / orbit", "rim lighting, high contrast"),
    "tense":         ShotDirectives("dutch-angle medium shot", "handheld micro-shake", "low-key, harsh shadows"),
    "introspective": ShotDirectives("close-up", "slow push-in", "soft Rembrandt window light"),
    "majestic":      ShotDirectives("extreme wide shot", "drone flyover", "golden-hour, volumetric god rays"),
    "melancholic":   ShotDirectives("profile medium shot", "slow pull-out", "blue-hour, desaturated"),
    "clean_product": ShotDirectives("centered product hero", "subtle micro-rotation, slow push-in", "soft studio key, gentle rim"),
}

# Per-platform short-video defaults (aspect, target seconds).
PLATFORM_VIDEO: dict[str, tuple[str, int]] = {
    "youtube": ("9:16", 30),    # Shorts
    "tiktok":  ("9:16", 15),
    "reels":   ("9:16", 15),
    "x":       ("16:9", 12),
    "linkedin": ("1:1", 12),
}

_NO_TEXT = (
    "No on-image text, no captions, no logos, no UI, no watermark "
    "(exact copy is added deterministically downstream)."
)


def cinematic_video_prompt(
    subject: str,
    action: str,
    environment: str,
    intent: str = "majestic",
    lens: str = "shallow depth of field, anamorphic",
    extra: str = "",
) -> str:
    """Build a model-ready cinematic video prompt.

    Formula (cinema-director): [shot] + [subject/action] + [environment]
    + [lighting] + [camera movement] + [lens]. Physics-logic phrasing
    (light on surfaces) is encouraged to trigger model reasoning.
    """
    d = INTENT_MAP.get(intent, INTENT_MAP["majestic"])
    parts = [
        d.framing + ":",
        f"{subject} {action}".strip(),
        f"in {environment}" if environment else "",
        f"lighting: {d.lighting}",
        f"camera: {d.movement}",
        f"lens: {lens}" if lens else "",
        extra.strip(),
        _NO_TEXT,
    ]
    return ". ".join(p for p in parts if p).replace("..", ".")


def ugc_hero_image_prompt(
    person_desc: str,
    product_name: str,
    environment: str,
    wearable: bool = False,
) -> str:
    """Director-grade lifestyle hero-image prompt for a UGC ad still.

    Adapted from the ugc-video-factory recipe: fuse a person + product
    into one ultra-realistic 9:16 lifestyle photo, product as focus,
    soft natural daylight, shallow DOF. This still then feeds an
    image-to-video call.
    """
    hold = (
        "the person wears the product naturally"
        if wearable
        else "the person holds the product naturally"
    )
    return (
        f"Ultra-realistic lifestyle photography: {person_desc} with {product_name} "
        f"in {environment}. {hold}. The product is clearly visible and is the main "
        "focus; any product logo or label stays legible and unchanged. Natural, "
        "modern, minimalist look. Lighting: soft natural daylight. Background: clean, "
        "aesthetic, slightly blurred (shallow depth of field). Style: high-end "
        "commercial lifestyle photography, realistic textures, 4K, vertical 9:16, "
        "social-media advertising. Keep the person's facial details unchanged."
    )


def illustrative_image_prompt(
    subject: str,
    style: str = "modern minimal editorial illustration",
    palette: str = "dark charcoal background with a single bright accent",
    composition: str = "centered, generous negative space",
) -> str:
    """Structured 'reasoning brief' for a TEXT-FREE illustrative still.

    Adapted from the nano-banana recipe (structured briefs over keyword
    stuffing). Diffusion is used here ONLY for illustration/photoreal —
    never for copy or numbers — so the no-text directive is explicit.
    """
    return (
        f"Subject: {subject}. Style: {style}. Palette: {palette}. "
        f"Composition: {composition}. High detail, crisp, social-media ready. "
        f"{_NO_TEXT}"
    )


def platform_video_spec(platform: str) -> tuple[str, int]:
    """(aspect_ratio, target_seconds) default for a platform."""
    return PLATFORM_VIDEO.get(platform, ("9:16", 15))
