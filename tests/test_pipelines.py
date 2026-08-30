"""PIPELINE — the deliberate scoped-run registry (discovery / content / orm)."""
from __future__ import annotations

from types import SimpleNamespace

from glitch_signal.agent.cron import schedule as sched
from glitch_signal.agent.loop import pipelines, scopes


# ── registry / resolve ────────────────────────────────────────────────
def test_registry_has_the_three_pipelines():
    assert set(pipelines.names()) == {"discovery", "content", "orm"}


def test_resolve_is_case_insensitive_and_unknown_is_none():
    assert pipelines.resolve("DISCOVERY").name == "discovery"
    assert pipelines.resolve(" orm ").name == "orm"
    assert pipelines.resolve("nope") is None
    assert pipelines.resolve(None) is None


def test_every_pipeline_scope_is_a_real_scope():
    """A pipeline must never name a scope that resolves to the `chat` fallback by accident."""
    for p in pipelines.registry().values():
        assert scopes.resolve(p.scope).name == p.scope   # exact, not fallen-back


def test_goal_templates_brand_and_forbids_publishing():
    for name in pipelines.names():
        g = pipelines.resolve(name).render_goal("acme")
        assert "acme" in g and "{brand}" not in g          # substituted
        gl = g.lower()
        assert "do not" in gl and any(w in gl for w in ("publish", "post", "email"))  # no-effect boundary


def test_schedules_validate_against_the_scheduler():
    for p in pipelines.registry().values():
        sched.validate(p.schedule, p.schedule_kind)         # raises if malformed


# ── discovery requires its kill-switch ─────────────────────────────────
def test_discovery_requires_discovery_flag(monkeypatch):
    disc = pipelines.resolve("discovery")
    monkeypatch.setattr(pipelines, "settings",
                        lambda: SimpleNamespace(agent_discovery_enabled=False))
    assert disc.missing_requirements() == ["agent_discovery_enabled"]
    monkeypatch.setattr(pipelines, "settings",
                        lambda: SimpleNamespace(agent_discovery_enabled=True))
    assert disc.missing_requirements() == []


def test_content_and_orm_have_no_required_switches():
    assert pipelines.resolve("content").missing_requirements() == []
    assert pipelines.resolve("orm").missing_requirements() == []


# ── content is caption-first unless media is opted in ──────────────────
def test_content_is_caption_first_by_default(monkeypatch):
    monkeypatch.setattr(pipelines, "settings",
                        lambda: SimpleNamespace(agent_content_media_enabled=False))
    c = pipelines.resolve("content")
    assert c.scope == "content_draft"                        # no media capability
    assert not scopes.resolve(c.scope).allows("generate_media")
    assert "MEDIA BRIEF" in c.render_goal("acme")            # briefs, not generation
    assert "do not generate media" in c.render_goal("acme").lower()


def test_content_generates_media_when_opted_in(monkeypatch):
    monkeypatch.setattr(pipelines, "settings",
                        lambda: SimpleNamespace(agent_content_media_enabled=True))
    c = pipelines.resolve("content")
    assert c.scope == "content"
    assert scopes.resolve(c.scope).allows("generate_media")
    assert scopes.resolve(c.scope).allows("mcp__higgsfield__generate_image")
