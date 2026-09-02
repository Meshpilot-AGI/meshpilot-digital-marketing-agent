"""Prompt TECHNIQUE — pure functions that turn a loose idea into a model-ready brief.

Adapted (not copied) from the monorepo's `media/prompt_recipes.py`, which distilled the
Generative-Media-Skills recipes into prompt builders. The principle it encodes, and the reason the
last campaign's imagery was generic: a model is only as good as the structure of its brief. A bare
topic string produces stock; an explicit Subject / Style / Palette / Composition / Lighting brief in
full sentences produces something art-directed.

Everything here is a pure function — no I/O, no config — so it unit-tests trivially and the LLM step
that precedes it (see `plan.py`) stays optional rather than load-bearing.

ONE DELIBERATE DIVERGENCE from the original: `prompt_recipes` appended a hard "no on-image text"
directive to every diffusion prompt, because the diffusion models of the time could not set type and
copy was always composited downstream. Current models can — verified live on this brand's own
account. So the no-text rule now belongs to the ILLUSTRATIVE route only, and a POSTER route exists
where the model is asked to set a short headline itself. Choosing per route keeps the original's
intent (never let a model invent copy it wasn't given) without inheriting a limit that has expired.
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

    Structured brief over keyword soup: models reason about full descriptive sentences and ignore
    stacked adjectives like "8k, masterpiece, trending".
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
    """A conceptual still where the MODEL sets a short headline.

    The headline is passed in double quotes and marked verbatim: current models honour quoted copy,
    and the point of supplying it is that the model must never invent the words itself.
    """
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


# The subject vocabulary a backdrop may draw from. Explicit rather than left to the model, because
# handing it the HEADLINE as the subject is what produced literal metaphor objects — a post about
# trailing drawdown came back as a pulley and cable, which says nothing about trading. The reader is
# a trader; the frame should look like the room they work in.
# Every entry must read as a TRADING desk, not merely a desk. A generic workstation is
# interchangeable with any software brand — it builds no identity. The distinguishing element is
# always a screen carrying a trading interface, kept heavily defocused so it reads as "a trading
# terminal" in silhouette without ever resolving into legible figures (see _NO_INVENTED_FIGURES:
# any number the model painted would be one we invented).
BACKDROP_SUBJECTS = (
    "the bottom bezel of a widescreen trading monitor showing a heavily blurred dark trading "
    "terminal — soft rectangular panel shapes and a faint out-of-focus price ladder, no legible "
    "text or numbers — above the top row of a dark mechanical keyboard",
    "two stacked trading screens seen edge-on and far out of focus, their dark interface panels "
    "reduced to soft glowing blocks, beside a desk clock on a dark desk",
    "a curved ultrawide trading monitor cropped at the frame edge, its charting interface rendered "
    "as an unreadable blur of dark panels and one faint rising line, keyboard edge below",
    "a trading terminal screen reflected in the dark glossy surface of a desk, the reflection soft "
    "and unreadable, with a mouse and keyboard edge catching the screen glow",
    "a multi-monitor trading setup shot from behind and below, only the glowing edges and cable run "
    "visible, the interface an indistinct wash of dark panels",
)


def backdrop_prompt(seed: int, *, style: str, palette: str, banned: str = "") -> str:
    """A text-free backdrop built to CARRY TYPE, not to illustrate the headline.

    Two failures this exists to prevent, both observed live:

    1. Subject drift. The first version passed the headline text in as the subject, so the model
       illustrated the words — "trailing and static drawdown" became a pulley on a concrete plinth.
       Generic object photography, unrelated to trading, and exactly the stock-metaphor look the
       brand's visual direction rules out. The subject is now drawn from a fixed workstation
       vocabulary and never from the copy.

    2. Composition drift. The first version said the subject "sits low and small" — one soft clause,
       which the model ignored, putting the subject through the middle of the type. The constraint
       is now stated as a PROPORTION and repeated, which it obeys.

    `seed` rotates the subject so consecutive posts do not share a frame; it is the caller's, so
    rendering is reproducible.
    """
    subject = BACKDROP_SUBJECTS[seed % len(BACKDROP_SUBJECTS)]
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
