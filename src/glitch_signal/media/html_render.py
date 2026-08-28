"""Deterministic design-as-code image renderer (GROW-SOCIAL-RENDER-2).

The problem: diffusion image models (gpt-image-2, Ideogram, Flux, ...)
render what text *looks like*, not what it *says* — so headlines and
numbers come out garbled ("Same cat $100k" instead of "cap", scrambled
axis labels). For anything that must show exact copy or figures, that is
disqualifying.

The fix (the consensus production pattern, e.g. SuperDesign): generate
the design as HTML/CSS with the copy as REAL text, then render to PNG
with headless Chrome. Text is pixel-perfect because it is actual
rendered type, fully brand-controlled, deterministic, and free.

Diffusion stays the right tool for photoreal / illustrative backgrounds
(see media/image_gen.py) — this module owns the text-accurate surface:
stat cards, comparison tables, quote cards, hook cards.

No new Python deps: shells out to an installed Chrome/Chromium with
`--headless --screenshot`. Brand look is resolved per-brand (Mesh Pilot
is multi-tenant; an unknown client gets a neutral default, never another
tenant's theme). Output matches image_gen.py: a PNG under
`{video_storage_path}/images/{brand_id}/`.
"""
from __future__ import annotations

import html as _html
import pathlib
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

AspectRatio = Literal["1:1", "4:5", "16:9", "9:16"]

# Logical card dimensions per aspect (Chrome renders at 2x for crispness).
_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "16:9": (1600, 900),
    "9:16": (1080, 1920),
}

_CHROME_CANDIDATES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "/snap/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/chromium-browser",
)


class HtmlRenderError(RuntimeError):
    """Raised when no Chrome binary is found or the screenshot fails."""


@dataclass(frozen=True)
class Theme:
    bg: str = "#15171a"
    fg: str = "#e8eef2"
    muted: str = "#9fb0bd"
    accent: str = "#2dd4bf"
    font: str = "Arial, Helvetica, sans-serif"


# Per-brand themes. Mesh Pilot is multi-tenant — Glitch Executor is
# client #1, not the product. Unknown brand -> neutral default.
_THEMES: dict[str, Theme] = {
    "glitch_executor": Theme(),               # default theme IS GE's look
    "glitch-executor": Theme(),               # tolerate both id spellings
}
_DEFAULT_THEME = Theme(accent="#6366f1")      # neutral indigo for other clients


def theme_for(brand_id: str) -> Theme:
    return _THEMES.get(brand_id, _DEFAULT_THEME)


@dataclass
class CardSpec:
    """Structured, text-accurate card content. Every field is real text."""
    headline: str
    eyebrow: str = ""
    subhead: str = ""
    # Optional 2-column comparison rows: [{"label","a","b"}] with a/b headers.
    rows: list[dict[str, str]] = field(default_factory=list)
    col_a: str = ""
    col_b: str = ""
    # Optional simple bullet list (used when `rows` is empty).
    bullets: list[str] = field(default_factory=list)
    footer: str = ""


def _esc(s: str) -> str:
    return _html.escape(s or "", quote=True)


def build_card_html(spec: CardSpec, theme: Theme, width: int, height: int) -> str:
    """Pure: turn a CardSpec + theme into a self-contained HTML string.

    Inline CSS only (no CDN) so rendering is deterministic and offline.
    """
    blocks: list[str] = []
    if spec.eyebrow:
        blocks.append(f'<div class="ey">{_esc(spec.eyebrow)}</div>')
    blocks.append(f'<h1 class="h">{_esc(spec.headline)}</h1>')
    if spec.subhead:
        blocks.append(f'<div class="s">{_esc(spec.subhead)}</div>')

    if spec.rows:
        head = ""
        if spec.col_a or spec.col_b:
            head = (
                '<tr><th></th>'
                f'<th>{_esc(spec.col_a)}</th><th>{_esc(spec.col_b)}</th></tr>'
            )
        body = "".join(
            f'<tr><td class="lbl">{_esc(r.get("label",""))}</td>'
            f'<td>{_esc(r.get("a",""))}</td><td>{_esc(r.get("b",""))}</td></tr>'
            for r in spec.rows
        )
        blocks.append(f'<table class="cmp">{head}{body}</table>')
    elif spec.bullets:
        items = "".join(f"<li>{_esc(b)}</li>" for b in spec.bullets)
        blocks.append(f'<ul class="bl">{items}</ul>')

    if spec.footer:
        blocks.append(f'<div class="ft">{_esc(spec.footer)}</div>')

    body_html = "\n".join(blocks)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0}}
.card{{width:{width}px;height:{height}px;background:{theme.bg};color:{theme.fg};
font-family:{theme.font};box-sizing:border-box;padding:90px;display:flex;
flex-direction:column;justify-content:center;overflow:hidden}}
.ey{{color:{theme.accent};font-size:30px;font-weight:700;letter-spacing:3px;
text-transform:uppercase;margin-bottom:18px}}
.h{{font-size:84px;font-weight:800;line-height:1.04;margin:0}}
.s{{font-size:38px;color:{theme.muted};margin-top:26px;line-height:1.3}}
.cmp{{margin-top:46px;border-collapse:collapse;width:100%;font-size:34px}}
.cmp th{{color:{theme.muted};text-align:left;font-weight:600;padding:10px 18px;font-size:28px}}
.cmp td{{padding:14px 18px;border-top:2px solid rgba(255,255,255,.08)}}
.cmp .lbl{{color:{theme.muted}}}
.cmp td:nth-child(2),.cmp th:nth-child(2){{color:{theme.accent};font-weight:700}}
.bl{{margin-top:36px;padding-left:0;list-style:none;font-size:36px;line-height:1.6}}
.bl li{{padding-left:42px;position:relative}}
.bl li:before{{content:"";position:absolute;left:0;top:18px;width:18px;height:4px;
background:{theme.accent}}}
.ft{{margin-top:auto;padding-top:40px;color:{theme.muted};font-size:28px;letter-spacing:1px}}
</style></head><body><div class="card">
{body_html}
</div></body></html>"""


def _chrome_bin() -> str:
    for c in _CHROME_CANDIDATES:
        if shutil.which(c) or pathlib.Path(c).exists():
            return c
    raise HtmlRenderError(
        f"no Chrome/Chromium binary found (tried {_CHROME_CANDIDATES})"
    )


def render_html_to_png(
    html_str: str,
    out_path: pathlib.Path,
    width: int,
    height: int,
    scale: int = 2,
) -> pathlib.Path:
    """Render an HTML string to a PNG via headless Chrome. Returns out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chrome = _chrome_bin()
    with tempfile.TemporaryDirectory() as td:
        html_path = pathlib.Path(td) / "card.html"
        html_path.write_text(html_str, encoding="utf-8")
        # Unique --user-data-dir per invocation: without it concurrent headless
        # Chrome runs contend on a singleton profile lock and hang (observed:
        # 120s timeout). Isolating the profile makes renders independent.
        profile_dir = pathlib.Path(td) / "profile"
        cmd = [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--hide-scrollbars", "--default-background-color=00000000",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            f"--user-data-dir={profile_dir}",
            f"--force-device-scale-factor={scale}",
            f"--window-size={width},{height}",
            f"--screenshot={out_path}",
            html_path.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise HtmlRenderError(
                f"chrome screenshot produced no file (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout)[:300]}"
            )
    log.info("html_render.png", path=str(out_path), bytes=out_path.stat().st_size,
             dims=f"{width}x{height}@{scale}x")
    return out_path


def render_card(
    spec: CardSpec,
    brand_id: str,
    aspect: AspectRatio = "16:9",
    out_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Build + render a text-accurate card for a brand. Returns the PNG path.

    Honors DISPATCH_MODE=dry_run (returns a non-existent placeholder path,
    matching media/image_gen.py's contract) and writes under
    {video_storage_path}/images/{brand_id}/ otherwise.
    """
    width, height = _DIMS.get(aspect, _DIMS["16:9"])
    theme = theme_for(brand_id)
    html_str = build_card_html(spec, theme, width, height)

    if out_dir is None:
        # Lazy import so build_card_html/render_html_to_png stay usable
        # (and unit-testable) without the glitch_signal config env.
        from glitch_signal.config import settings

        s = settings()
        if getattr(s, "is_dry_run", False):
            log.info("html_render.dry_run", brand_id=brand_id, headline=spec.headline[:60])
            return pathlib.Path(f"/tmp/dry-run-card-{uuid.uuid4().hex[:8]}.png")
        out_dir = pathlib.Path(s.video_storage_path) / "images" / brand_id

    out_path = pathlib.Path(out_dir) / f"{uuid.uuid4().hex}.png"
    return render_html_to_png(html_str, out_path, width, height)
