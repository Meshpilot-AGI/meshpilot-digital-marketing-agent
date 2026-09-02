"""Smoke tests for Glitch Signal.

All tests use DISPATCH_MODE=dry_run and mock external API calls.
These run without any network access or real credentials.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC

import pytest

# Force dry-run for all tests
os.environ["DISPATCH_MODE"] = "dry_run"
os.environ["SIGNAL_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["TELEGRAM_BOT_TOKEN_SIGNAL"] = "0:test"
os.environ["TELEGRAM_ADMIN_IDS"] = "0"
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["GOOGLE_API_KEY"] = "test"


# ORM/engagement guardrail + classifier tests removed in PRUNE-1 (subsystem deleted).


# ---------------------------------------------------------------------------
# 2. VideoRouter — deterministic, no LLM, no DB
# ---------------------------------------------------------------------------

class TestServerHealth:
    async def test_healthz_returns_ok(self):
        """`queue` is gone: it counted `scheduled_post` / `video_job`, both dropped with the legacy
        pipeline. Health now reports only what this service actually runs."""
        from glitch_signal import server as srv

        result = await srv.healthz()
        assert result["status"] == "ok"
        assert result["service"] == "glitch-signal"
        assert "dispatch_mode" in result
        assert "queue" not in result


# ---------------------------------------------------------------------------
# 7. Config loading
# ---------------------------------------------------------------------------

class TestConfig:
    def test_is_dry_run(self):
        from glitch_signal.config import settings
        s = settings()
        assert s.is_dry_run is True  # set at top of this file

    def test_brand_config_loads_defaults(self):
        from glitch_signal.config import brand_config
        bc = brand_config()
        assert bc["brand"]["accent_color"] == "#00ff88"
        assert bc["brand"]["base_color"] == "#0a0a0f"
        assert "hard_stop_phrases" in bc["orm_guardrails"]

    def test_github_repo_list(self):
        from glitch_signal.config import Settings
        s = Settings(github_repos="glitch-cod-confirm,glitch-grow-ads-agent")
        assert s.github_repo_list == ["glitch-cod-confirm", "glitch-grow-ads-agent"]


def test_lifespan_runs_startup_and_shutdown(monkeypatch):
    # #107: startup/shutdown now run via the lifespan context manager (not deprecated on_event).
    from fastapi.testclient import TestClient

    import glitch_signal.server as server

    events = []
    monkeypatch.setattr(server, "get_graph", lambda: "graph", raising=False)

    async def _start():
        events.append("start")

    async def _stop():
        events.append("stop")

    monkeypatch.setattr(server, "_on_startup", _start)
    monkeypatch.setattr(server, "_on_shutdown", _stop)
    with TestClient(server.app):
        pass  # entering/exiting the context drives lifespan
    assert events == ["start", "stop"]
