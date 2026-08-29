"""AGENT-POLICY — deterministic tool-call gate (pure, no network/DB)."""
from __future__ import annotations

from glitch_signal.agent.loop import policy
from glitch_signal.agent.loop.policy import Policy


# ── publish kill-switch ───────────────────────────────────────────────
def test_publish_denied_when_disabled():
    p = Policy(publish_enabled=False)
    for t in ["publish", "post", "publish_instagram", "buffer_post"]:
        d = p.check(t, {}, "glitch_executor")
        assert d.allow is False and "disabled" in d.reason


def test_publish_allowed_when_enabled():
    p = Policy(publish_enabled=True)
    assert p.check("publish", {}, "glitch_executor").allow is True


# ── read/memory tools always allowed ──────────────────────────────────
def test_non_publish_tools_allowed():
    p = Policy()
    for t in ["recall", "remember", "list_recipes"]:
        assert p.check(t, {}, "b").allow is True


# ── per-run media budget (cost control) ───────────────────────────────
def test_media_budget_enforced():
    p = Policy(max_media_per_run=2)
    assert p.check("generate_media", {}, "b", counts={"generate_media": 0}).allow is True
    assert p.check("generate_media", {}, "b", counts={"generate_media": 1}).allow is True
    d = p.check("generate_media", {}, "b", counts={"generate_media": 2})
    assert d.allow is False and "budget" in d.reason


# ── per-brand explicit deny ───────────────────────────────────────────
def test_per_brand_deny():
    p = Policy(brand_denied={"acme": frozenset({"generate_media"})})
    assert p.check("generate_media", {}, "acme").allow is False
    assert p.check("generate_media", {}, "other").allow is True  # only acme denied


# ── back-compat allow() + config wiring ───────────────────────────────
def test_allow_wrapper_denies_publish_by_default():
    allowed, reason = policy.allow("publish", {}, "b")
    assert allowed is False and reason


def test_allow_wrapper_permits_recall():
    allowed, _ = policy.allow("recall", {}, "b")
    assert allowed is True


def test_from_config_defaults_publishing_off():
    p = policy.from_config()
    assert p.publish_enabled is False               # safe default
    assert p.check("publish", {}, "b").allow is False
