"""Meta Graph API version pin.

Bumped v21 -> v26 after verifying, not assuming: the page node, the IG user node and /{ig}/media
behave identically on both; the app reports zero deprecations; and the insights-metric probe gives
the same result on v21, v23 and v26 (so the missing distribution metrics are NOT a version artifact).
"""
import os

from glitch_signal.config import Settings


def test_default_is_the_current_platform_version():
    assert Settings().meta_graph_api_version == "v26.0"


def test_version_is_env_overridable_for_rollback():
    """A bad platform version must be reversible by config, not by a deploy — the API surface is
    outside our control and a regression could appear long after the bump."""
    prev = os.environ.get("META_GRAPH_API_VERSION")
    os.environ["META_GRAPH_API_VERSION"] = "v21.0"
    try:
        assert Settings().meta_graph_api_version == "v21.0"
    finally:
        if prev is None:
            os.environ.pop("META_GRAPH_API_VERSION", None)
        else:
            os.environ["META_GRAPH_API_VERSION"] = prev


def test_every_meta_module_agrees_on_the_default():
    """The influencer modules read the env directly at IMPORT time rather than through settings, so
    a bump has to touch them too or half the codebase silently stays on the old version."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "glitch_signal"
    found = set()
    for f in root.rglob("*.py"):
        for m in re.finditer(r'META_GRAPH_API_VERSION",\s*"(v\d+\.\d+)"', f.read_text()):
            found.add(m.group(1))
    assert found <= {"v26.0"}, f"modules pinned to a stale Graph version: {found}"
