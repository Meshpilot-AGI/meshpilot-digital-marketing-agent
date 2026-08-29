"""Playbook library — frontmatter parsing, loader, and the loop tools."""
from __future__ import annotations

import pytest

from glitch_signal.agent.playbooks import loader


def test_parse_frontmatter(tmp_path):
    d = tmp_path / "my-playbook"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: my-playbook\ndescription: teaches X; use when Y\n---\n\n# Body\n\nreal content here",
        encoding="utf-8",
    )
    pb = loader._parse(d / "SKILL.md")
    assert pb.slug == "my-playbook"
    assert pb.description == "teaches X; use when Y"
    assert pb.body.startswith("# Body") and "real content here" in pb.body


def test_parse_without_frontmatter_falls_back(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    (d / "SKILL.md").write_text("# Just a body, no frontmatter", encoding="utf-8")
    pb = loader._parse(d / "SKILL.md")
    assert pb.slug == "raw" and pb.name == "raw" and pb.description == ""


def test_library_loads_the_real_handbooks():
    loader._library.cache_clear()
    pbs = {p.slug: p for p in loader.list_playbooks()}
    # the brought/authored handbooks must be present and described
    for slug in ("paid-media-auditor", "seo-audit", "social-copy", "youtube", "orm"):
        assert slug in pbs, f"missing playbook: {slug}"
        assert pbs[slug].description, f"{slug} has no description"
        assert len(pbs[slug].body) > 200, f"{slug} body looks empty"


async def test_read_playbook_tool_returns_body():
    from glitch_signal.agent.loop import tools

    out = await tools.execute("read_playbook", {"slug": "social-copy"}, "glitch_executor")
    assert "ERROR" not in out and len(out) > 200


async def test_read_playbook_tool_unknown_slug():
    from glitch_signal.agent.loop import tools

    out = await tools.execute("read_playbook", {"slug": "does-not-exist"}, "glitch_executor")
    assert out.startswith("ERROR")


async def test_list_playbooks_tool():
    from glitch_signal.agent.loop import tools

    out = await tools.execute("list_playbooks", {}, "glitch_executor")
    assert "paid-media-auditor" in out and "social-copy" in out
