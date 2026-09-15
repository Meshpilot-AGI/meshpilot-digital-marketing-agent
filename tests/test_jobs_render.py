"""JOBS-4b — the CV renderer. ATS-safety is a hard constraint, so it is tested as one."""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs.render import build_cv_html, markdown_to_html_body, render_cv_pdf

MD = """# CV -- Tejas Karan Agrawal

**Location:** Toronto, ON
**Email:** a@b.com

## Professional Summary

Performance marketer with 6+ years. Led a ~$30K/day account.

## Work Experience

### Quickads

**Performance Marketing Specialist**

- Led the team running Udemy's paid account at ~$30K/day
- Iterated ad sets against CTR, CPA and ROAS targets

## Skills

- **Paid Media:** Meta Ads, Google Ads
"""


# --- markdown subset ------------------------------------------------------------------

def test_headings_become_real_heading_tags():
    """An ATS finds sections by heading text — they must be headings, not styled divs."""
    html = markdown_to_html_body(MD)
    assert "<h1>" in html and "<h2>" in html and "<h3>" in html
    assert "Work Experience" in html and "Skills" in html


def test_bullets_become_a_real_list():
    html = markdown_to_html_body(MD)
    assert html.count("<ul>") == html.count("</ul>") >= 2
    assert "<li>" in html


def test_inline_emphasis_is_converted():
    assert "<strong>Location:</strong>" in markdown_to_html_body("**Location:** Toronto")
    assert "<em>x</em>" in markdown_to_html_body("*x*")


def test_html_in_the_markdown_is_escaped_not_executed():
    """Tailored markdown comes from a model. It must never inject markup into the CV."""
    html = markdown_to_html_body("- <script>alert(1)</script> and <b>raw</b>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_unclosed_list_is_closed():
    html = markdown_to_html_body("- a\n- b")
    assert html.count("<ul>") == html.count("</ul>") == 1


# --- ATS-safe layout is structural, not cosmetic --------------------------------------

def test_layout_has_no_multi_column_or_table_furniture():
    """Multi-column and table layouts interleave when linearised — the classic way a good CV
    parses as nonsense."""
    html = build_cv_html(MD).lower()
    for banned in ("<table", "column-count", "display:grid", "display: grid", "float:", "position:absolute"):
        assert banned not in html, f"ATS-hostile layout: {banned}"


def test_page_header_footer_is_disabled():
    """Chrome's print header/footer region is dropped by many parsers."""
    import inspect

    from glitch_signal.agent.jobs import render

    assert "--no-pdf-header-footer" in inspect.getsource(render.render_cv_pdf)


def test_empty_markdown_is_refused():
    from glitch_signal.media.html_render import HtmlRenderError

    with pytest.raises(HtmlRenderError):
        render_cv_pdf("   ")


# --- the real thing: a PDF whose TEXT survives ----------------------------------------

def _chrome_available() -> bool:
    from glitch_signal.media.html_render import _chrome_bin

    try:
        _chrome_bin()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _chrome_available(), reason="no Chrome/Chromium available")
def test_renders_a_pdf_whose_text_layer_is_machine_readable(tmp_path):
    """The whole point. A PDF that looks right but has no text layer is worse than plain text,
    because it fails invisibly — the human sees a nice CV and the parser sees nothing."""
    pypdf = pytest.importorskip("pypdf")
    out = render_cv_pdf(MD, tmp_path / "cv.pdf")
    assert out.exists() and out.stat().st_size > 1000

    text = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(out)).pages)
    for probe in ["Tejas Karan Agrawal", "a@b.com", "Quickads", "Udemy", "30K/day"]:
        assert probe in text, f"{probe!r} did not survive into the PDF text layer"


@pytest.mark.skipif(not _chrome_available(), reason="no Chrome/Chromium available")
def test_render_is_deterministic_enough_to_be_reviewable(tmp_path):
    a = render_cv_pdf(MD, tmp_path / "a.pdf")
    b = render_cv_pdf(MD, tmp_path / "b.pdf")
    assert abs(a.stat().st_size - b.stat().st_size) < 4096


def test_chrome_discovery_prefers_the_headless_shell():
    """macOS's full Google Chrome.app with --headless=new was measured HANGING to the 120s
    timeout even with an isolated --user-data-dir. The headless shell starts immediately."""
    import inspect

    from glitch_signal.media import html_render

    src = inspect.getsource(html_render._chrome_bin)
    assert "_playwright_chromium()" in src
    assert "/Applications/" in src, "desktop Chrome must be tried only as a last resort"
