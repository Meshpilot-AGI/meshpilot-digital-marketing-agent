"""Prompt TECHNIQUE — pure functions that turn a loose idea into a model-ready brief.

Adapted from the monorepo's `media/prompt_recipes.py`. A bare topic string produces stock imagery;
an explicit Subject / Style / Palette / Composition / Lighting brief in full sentences produces
something art-directed.

Pure functions only (no I/O, no config), so the LLM step that precedes this (`plan.py`) stays
optional rather than load-bearing.

Divergence from the original: `prompt_recipes` banned on-image text everywhere because older
diffusion models couldn't set type. Current models can (verified live), so the no-text rule now
applies only to the ILLUSTRATIVE route; a POSTER route lets the model set a supplied headline
verbatim instead — same intent (never let the model invent copy), without the expired limitation.
"""
from __future__ import annotations

# Aspect defaults per platform. Portrait wherever the feed rewards height.
PLATFORM_ASPECT: dict[str, str] = {
    "instagram": "4:5",
    "facebook": "4:5",
    "linkedin": "1:1",
    "x": "16:9",
    "tiktok": "9:16",
    "youtube": "9:16",
}
DEFAULT_ASPECT = "4:5"

_NO_TEXT = (
    "Render NO text, letters, numbers, captions, logos, UI or watermark anywhere in the image — "
    "the copy is composited deterministically downstream."
)

_NO_INVENTED_FIGURES = (
    "Show no numbers, prices, percentages, balances, axis values or chart figures of any kind: any "
    "figure would be invented and this brand publishes none it does not have."
)


def aspect_for(platform: str) -> str:
    return PLATFORM_ASPECT.get((platform or "").lower(), DEFAULT_ASPECT)


def illustrative_prompt(subject: str, *, style: str, palette: str,
                        composition: str = "single clear focal point, generous negative space",
                        banned: str = "") -> str:
    """A TEXT-FREE conceptual still. Copy lives in the caption or is composited on top.

    Full descriptive sentences over keyword soup — models reason about the former and ignore stacked
    adjectives like "8k, masterpiece, trending".
    """
    parts = [
        f"Subject: {subject}.",
        f"Style: {style}.",
        f"Palette: {palette}.",
        f"Composition: {composition}.",
        "Lighting: physically consistent — describe how light actually falls on the surfaces.",
        f"Avoid entirely: {banned}." if banned else "",
        _NO_INVENTED_FIGURES,
        _NO_TEXT,
    ]
    return " ".join(p for p in parts if p)


def poster_prompt(subject: str, headline: str, *, style: str, palette: str,
                  banned: str = "") -> str:
    """A conceptual still where the MODEL sets a short headline, passed quoted and verbatim — current
    models honour quoted copy, so the words are always supplied, never invented."""
    parts = [
        f"Subject: {subject}.",
        f'Set this exact headline in the image, verbatim, spelled precisely: "{headline}".',
        "Typography: clean grotesque sans, high contrast against the ground, generous margins, "
        "placed so it never crowds the subject. No other text of any kind.",
        f"Style: {style}.",
        f"Palette: {palette}.",
        "Lighting: physically consistent — describe how light actually falls on the surfaces.",
        f"Avoid entirely: {banned}." if banned else "",
        _NO_INVENTED_FIGURES,
    ]
    return " ".join(p for p in parts if p)


def video_prompt(subject: str, *, style: str, palette: str, banned: str = "",
                 orientation: str = "portrait") -> str:
    """A short generative-video brief. Same structure, plus camera and duration cues."""
    parts = [
        f"Subject: {subject}.",
        f"Style: {style}.",
        f"Palette: {palette}.",
        "Camera: slow deliberate push-in or gentle orbit — no whip pans, no rapid cuts.",
        "Motion: restrained and physical; objects behave with real weight.",
        f"Orientation: {orientation}.",
        f"Avoid entirely: {banned}." if banned else "",
        _NO_INVENTED_FIGURES,
    ]
    return " ".join(p for p in parts if p)


# NEUTRAL fallback subject vocabulary — used only when a brand declares no `subjects` of its own.
#
# Subject is never taken from the headline: handing the model the headline made it illustrate the
# words (a post about trailing drawdown came back as a pulley and cable). So the subject is drawn
# from a fixed vocabulary — but that vocabulary belongs to the BRAND, not to this module. These
# entries are deliberately industry-free desk surfaces: a brand that declares nothing still gets a
# usable backdrop, and no brand inherits another brand's industry. GE's trading-desk vocabulary
# lives in its positioning row's `visual.subjects`.
BACKDROP_SUBJECTS = (
    "the bottom bezel of a widescreen monitor showing a heavily blurred dark interface — soft "
    "rectangular panel shapes with no legible text or numbers — above the top row of a dark "
    "mechanical keyboard",
    "two stacked screens seen edge-on and far out of focus, their dark interface panels reduced to "
    "soft glowing blocks, beside a desk clock on a dark desk",
    "a curved ultrawide monitor cropped at the frame edge, its interface rendered as an unreadable "
    "blur of dark panels and one faint bright line, keyboard edge below",
    "a screen reflected in the dark glossy surface of a desk, the reflection soft and unreadable, "
    "with a mouse and keyboard edge catching the screen glow",
    "a multi-monitor desk setup shot from behind and below, only the glowing edges and cable run "
    "visible, the interface an indistinct wash of dark panels",
)


def backdrop_prompt(seed: int, *, style: str, palette: str, banned: str = "",
                    subjects: tuple[str, ...] | list[str] = ()) -> str:
    """A text-free backdrop built to CARRY TYPE, not to illustrate the headline.

    Two failures observed live and fixed here: passing the headline as subject made the model
    illustrate the words (a stock-metaphor look the brand direction rules out) — subject is now
    drawn only from the fixed workstation vocabulary; and a soft "sits low and small" clause was
    ignored, putting the subject through the type — now stated as a repeated PROPORTION, which holds.

    `seed` (caller-supplied, for reproducibility) rotates the subject across posts.

    `subjects` is the BRAND's own imagery vocabulary, from its positioning row. It defaults to
    `BACKDROP_SUBJECTS`, which is a deliberately NEUTRAL desk vocabulary — a brand that declares
    nothing still gets a usable backdrop, and no brand inherits another brand's industry.
    """
    pool = tuple(subjects) or BACKDROP_SUBJECTS
    subject = pool[seed % len(pool)]
    parts = [
        "Vertical frame for a text overlay.",
        "COMPOSITION IS THE PRIORITY: the top 70 percent of the frame is pure empty unlit near-black "
        "void, completely bare, with no objects in it at all.",
        f"Only along the very BOTTOM EDGE, cropped off by the frame border, is {subject}, "
        "shot from a low angle and heavily out of focus with shallow depth of field.",
        "The middle of the frame stays empty darkness.",
        f"Style: {style}.",
        f"Palette: {palette}.",
        "Lighting: a single faint accent glow spilling from the screen; everything else in shadow.",
        f"Avoid entirely: {banned}." if banned else "",
        _NO_INVENTED_FIGURES,
        _NO_TEXT,
    ]
    return " ".join(x for x in parts if x)
