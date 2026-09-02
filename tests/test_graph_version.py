"""Meta Graph API version pin.

Bumped v21 -> v26 after verifying, not assuming: the page node, the IG user node and /{ig}/media
behave identically on both; the app reports zero deprecations; and the insights-metric probe gives
the same result on v21, v23 and v26 (so the missing distribution metrics are NOT a version artifact).
"""
from glitch_signal.config import Settings


def test_default_is_the_current_platform_version(monkeypatch):
    """Isolate the process environment AND `.env` loading — `Settings` reads both, so this test must
    not depend on (or be broken by) a real META_GRAPH_API_VERSION override such as the documented
    v21 rollback, which would otherwise make this "default" test assert the override instead."""
    monkeypatch.delenv("META_GRAPH_API_VERSION", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    assert Settings().meta_graph_api_version == "v26.0"


def test_version_is_env_overridable_for_rollback(monkeypatch):
    """A bad platform version must be reversible by config, not by a deploy — the API surface is
    outside our control and a regression could appear long after the bump."""
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v21.0")
    assert Settings().meta_graph_api_version == "v21.0"


def test_every_meta_module_agrees_on_the_default():
    """The influencer modules read the env directly at IMPORT time rather than through settings, so
    a bump has to touch them too or half the codebase silently stays on the old version.

    Scans `src/`, `scripts/` and `docs/` — not just `src/glitch_signal`. The account-connection
    scripts and a standalone publisher live outside the package and still default/hardcode a Graph
    version, and the vendor runbook restates the current version in prose; a bump that only edits
    the package leaves all three silently stale.
    """
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    env_default = re.compile(r'META_GRAPH_API_VERSION",\s*"(v\d+\.\d+)"')
    hardcoded_url = re.compile(r'graph\.facebook\.com/(v\d+\.\d+)')
    doc_prose = re.compile(r'meta_graph_api_version`\s*\(currently\s*`(v\d+\.\d+)`\)')

    found = set()
    for f in (*(repo_root / "src").rglob("*.py"), *(repo_root / "scripts").rglob("*.py")):
        text = f.read_text()
        found.update(m.group(1) for m in env_default.finditer(text))
        found.update(m.group(1) for m in hardcoded_url.finditer(text))
    for f in (repo_root / "docs").rglob("*.md"):
        found.update(m.group(1) for m in doc_prose.finditer(f.read_text()))

    assert found <= {"v26.0"}, f"modules pinned to a stale Graph version: {found}"
