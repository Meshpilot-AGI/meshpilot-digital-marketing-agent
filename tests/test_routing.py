"""Model router (ROUTER) — tier resolution, rule-based classify, env override, metrics."""
from __future__ import annotations

from glitch_signal.agent.loop import routing


def test_resolve_tiers_quality_first():
    assert routing.resolve("critical")[0] == "anthropic/claude-opus-5"
    assert routing.resolve("complex")[0] == "anthropic/claude-sonnet-5"
    assert routing.resolve("moderate")[0] == "z-ai/glm-5.2"
    assert routing.resolve("simple")[0] == "anthropic/claude-haiku-4.5"
    assert len(routing.resolve("complex")) == 3           # primary + 2 fallbacks for native failover


def test_resolve_unknown_defaults_to_complex():
    assert routing.resolve("nonsense") == routing.TIERS["complex"]
    assert routing.resolve(None) == routing.TIERS["complex"]


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_ROUTER_SIMPLE", "x/model-a, x/model-b")
    assert routing.resolve("simple") == ["x/model-a", "x/model-b"]


def test_classify_rule_based():
    assert routing.classify("classify this short thing") == "simple"
    assert routing.classify("draft a campaign strategy for Q4") == "complex"
    assert routing.classify("do a final review of the launch architecture") == "critical"
    assert routing.classify("word " * 200) == "moderate"   # long-ish, no strong keyword


def test_metrics_record_and_report():
    routing._METRICS.clear()
    routing.record("m1", latency_ms=100, ok=True)
    routing.record("m1", latency_ms=200, ok=False)
    m = routing.metrics()
    assert m["models"]["m1"]["calls"] == 2 and m["models"]["m1"]["errors"] == 1
    assert m["models"]["m1"]["error_rate"] == 0.5 and m["models"]["m1"]["latency_ms_ewma"] > 0
    assert set(m["tiers"]) == {"critical", "complex", "moderate", "simple"}
