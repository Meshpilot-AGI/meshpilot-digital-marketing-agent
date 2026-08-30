"""web_search / web_fetch client tools (OpenRouter-backed, no network)."""
from __future__ import annotations

import json

import glitch_signal.agent.loop.tools as tools


async def test_web_search_calls_openrouter_web(monkeypatch):
    async def _cw(query, *, max_results=5, **k):
        assert "what is GE" in query
        return ("GE is a prop-firm trading platform", ["https://glitchexecutor.com"])

    monkeypatch.setattr("glitch_signal.agent.loop.llm.complete_web", _cw)
    out = await tools._t_web_search({"query": "what is GE"}, "b")
    d = json.loads(out)
    assert "trading platform" in d["answer"] and d["sources"] == ["https://glitchexecutor.com"]


async def test_web_search_missing_query():
    assert (await tools._t_web_search({}, "b")).startswith("ERROR")


async def test_web_search_failsoft(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("web down")
    monkeypatch.setattr("glitch_signal.agent.loop.llm.complete_web", _boom)
    out = await tools._t_web_search({"query": "x"}, "b")
    assert out.startswith("ERROR") and "web down" in out


async def test_web_fetch_strips_html(monkeypatch):
    class _R:
        text = "<html><head><style>x{}</style></head><body>Hello <b>world</b></body></html>"

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            return _R()

    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _C())
    out = await tools._t_web_fetch({"url": "https://x.com"}, "b")
    assert "Hello world" in out and "<b>" not in out and "x{}" not in out


async def test_web_fetch_missing_url():
    assert (await tools._t_web_fetch({}, "b")).startswith("ERROR")
