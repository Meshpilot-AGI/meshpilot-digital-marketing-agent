"""render_cv — tailored markdown → an ATS-safe PDF.

Reuses the Chrome binary `media/html_render.py` already depends on, with `--print-to-pdf` instead of
`--screenshot`. No new dependency: the design-as-code path in this repo is already "inline CSS,
headless Chrome, deterministic pixels", and a CV is the same problem with a different output format.

**ATS-safe is a hard constraint, not a style preference.** An applicant-tracking system parses the
PDF's text layer; anything that survives visually but not textually is worse than plain. So:

- **Single column.** Multi-column layouts interleave when linearised — the classic way a good CV
  parses as nonsense.
- **No tables, no text boxes, no headers/footers.** Chrome's page header/footer is explicitly
  disabled; many parsers drop that region, and contact details put there vanish.
- **Real selectable text**, never an image of text. Chrome's print-to-pdf preserves the text layer.
- **Standard font stack**, generous line height, no ligatures-only glyphs.
- Section headings as plain `<h2>` so a parser can find EXPERIENCE / EDUCATION / SKILLS.

The markdown converter here is deliberately small and hand-written rather than a dependency. A CV is
headings, bullets, bold and paragraphs; controlling the exact HTML is the point, because the HTML is
what the ATS eventually reads.
"""
from __future__ import annotations

import html as _html
import pathlib
import re
import subprocess
import tempfile
import uuid

import structlog

log = structlog.get_logger()

_INLINE = (
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"`([^`\n]+?)`"), r"<code>\1</code>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
)


def _inline(text: str) -> str:
    out = _html.escape(text, quote=False)
    for rx, rep in _INLINE:
        out = rx.sub(rep, out)
    return out


def markdown_to_html_body(md: str) -> str:
    """A deliberately small markdown subset: h1-h4, bullets, paragraphs, inline emphasis."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            continue
        m = re.match(r"^\s*[-*•]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1).strip())}</li>")
            continue
        if re.match(r"^\s*-{3,}\s*$", line):
            close_list()
            continue
        close_list()
        out.append(f"<p>{_inline(line.strip())}</p>")
    close_list()
    return "\n".join(out)


_CSS = """
@page { size: Letter; margin: 14mm 15mm; }
html, body { margin: 0; padding: 0; }
body {
  font-family: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif;
  font-size: 10.5pt; line-height: 1.42; color: #111; }
h1 { font-size: 19pt; margin: 0 0 2pt; letter-spacing: .2pt; }
h2 { font-size: 11.5pt; margin: 14pt 0 5pt; text-transform: uppercase;
     letter-spacing: .8pt; border-bottom: .8pt solid #999; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 9pt 0 1pt; }
h4 { font-size: 10.5pt; margin: 5pt 0 1pt; font-weight: 600; color: #333; }
p  { margin: 0 0 4pt; }
ul { margin: 3pt 0 6pt; padding-left: 14pt; }
li { margin: 0 0 3pt; }
a  { color: #111; text-decoration: none; }
strong { font-weight: 700; }
/* Keep a role's heading with its bullets rather than orphaning it at a page break. */
h2, h3 { break-after: avoid-page; page-break-after: avoid; }
li { break-inside: avoid-page; page-break-inside: avoid; }
"""


def build_cv_html(markdown: str) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f"<style>{_CSS}</style></head><body>{markdown_to_html_body(markdown)}</body></html>")


def render_cv_pdf(markdown: str, out_path: pathlib.Path | str | None = None) -> pathlib.Path:
    """Render tailored CV markdown to an ATS-safe PDF. Returns the path."""
    from glitch_signal.media.html_render import HtmlRenderError, _chrome_bin

    if not (markdown or "").strip():
        raise HtmlRenderError("render_cv: empty markdown")

    out = pathlib.Path(out_path) if out_path else pathlib.Path(
        tempfile.gettempdir()) / f"cv-{uuid.uuid4().hex[:10]}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    chrome = _chrome_bin()

    with tempfile.TemporaryDirectory() as td:
        html_path = pathlib.Path(td) / "cv.html"
        html_path.write_text(build_cv_html(markdown), encoding="utf-8")
        profile = pathlib.Path(td) / "profile"   # per-run profile: a shared one deadlocks (html_render)
        cmd = [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            # ⚠️ A container's /dev/shm is 64 MB by default and Chromium crashes when it exhausts
            # it — intermittently, which is the worst way to fail. The Playwright driver in this
            # same image already passes this flag and has never crashed; the PDF renderer did not,
            # and took down a real submission (DEPT 4.0, 2026-09-17). Keep the two flag sets in
            # step: they drive the same browser in the same container.
            "--disable-dev-shm-usage",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            f"--user-data-dir={profile}",
            # No page header/footer: many parsers drop that region, and a URL stamped there is noise
            # to a human reviewer.
            "--no-pdf-header-footer",
            f"--print-to-pdf={out}",
            html_path.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not out.exists() or out.stat().st_size == 0:
        raise HtmlRenderError(
            f"render_cv: chrome produced no pdf (rc={proc.returncode}): {(proc.stderr or '')[:300]}")
    log.info("jobs.render_cv", path=str(out), kb=out.stat().st_size // 1024)
    return out


def pdf_text(path: pathlib.Path | str) -> str:
    """Extract the PDF's text layer — used to PROVE the CV is machine-readable, not just pretty."""
    import pypdf

    reader = pypdf.PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)
