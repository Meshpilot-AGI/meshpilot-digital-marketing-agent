"""web_search / web_fetch client tools — OpenRouter-backed, gated, SSRF-guarded (no network)."""
from __future__ import annotations

import json

import glitch_signal.agent.loop.tools as tools


# ── web_search ────────────────────────────────────────────────────────
async def test_web_search_calls_openrouter_web(monkeypatch):
    async def _cw(query, *, max_results=5, **k):
        return ("GE is a prop-firm trading platform", ["https://glitchexecutor.com"])

    monkeypatch.setattr("glitch_signal.agent.loop.llm.complete_web", _cw)
    out = await tools._t_web_search({"query": "what is GE"}, "b")
    d = json.loads(out)
    assert "trading platform" in d["answer"] and d["sources"] == ["https://glitchexecutor.com"]


async def test_web_search_disabled(monkeypatch):
    monkeypatch.setenv("AGENT_WEB_SEARCH_ENABLED", "false")
    assert (await tools._t_web_search({"query": "x"}, "b")).startswith("ERROR: web_search is disabled")


async def test_web_search_missing_query():
    assert (await tools._t_web_search({}, "b")).startswith("ERROR")


# ── SSRF guard ────────────────────────────────────────────────────────
def test_web_url_ok_rejects_bad_scheme_and_private():
    assert tools._web_url_ok("ftp://example.com")[0] is False        # scheme
    assert tools._web_url_ok("file:///etc/passwd")[0] is False
    assert tools._web_url_ok("http://localhost/x")[0] is False       # loopback (127.0.0.1)
    assert tools._web_url_ok("http://127.0.0.1/x")[0] is False       # loopback
    assert tools._web_url_ok("http://169.254.169.254/latest/meta-data")[0] is False  # cloud metadata (link-local)


def test_web_url_ok_blocked_domain(monkeypatch):
    monkeypatch.setenv("AGENT_WEB_BLOCKED_DOMAINS", "evil.com, spam.io")
    assert tools._web_url_ok("https://evil.com/x")[0] is False
    assert tools._web_url_ok("https://sub.evil.com/x")[0] is False   # subdomain of a blocked domain


# ── web_fetch ─────────────────────────────────────────────────────────
class _StreamResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        yield self._body


class _StreamClient:
    def __init__(self, status=200, body=b""):
        self._status, self._body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **k):
        return _StreamResp(self._status, self._body)


async def test_web_fetch_strips_html(monkeypatch):
    monkeypatch.setattr(tools, "_web_url_ok", lambda u: (True, ""))
    monkeypatch.setattr("httpx.AsyncClient",
                        lambda **k: _StreamClient(200, b"<html><style>x{}</style><body>Hello <b>world</b></body></html>"))
    out = await tools._t_web_fetch({"url": "https://x.com"}, "b")
    assert "Hello world" in out and "<b>" not in out and "x{}" not in out


async def test_web_fetch_rejects_redirect(monkeypatch):
    monkeypatch.setattr(tools, "_web_url_ok", lambda u: (True, ""))
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _StreamClient(302, b""))
    assert (await tools._t_web_fetch({"url": "https://x.com"}, "b")).startswith("ERROR: web_fetch got a redirect")


async def test_web_fetch_http_error_not_returned_as_text(monkeypatch):
    monkeypatch.setattr(tools, "_web_url_ok", lambda u: (True, ""))
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _StreamClient(500, b"<html>error page</html>"))
    out = await tools._t_web_fetch({"url": "https://x.com"}, "b")
    assert out.startswith("ERROR: web_fetch got HTTP 500") and "error page" not in out


async def test_web_fetch_refused_on_ssrf():
    assert (await tools._t_web_fetch({"url": "http://127.0.0.1/x"}, "b")).startswith("ERROR: web_fetch refused")


async def test_web_fetch_disabled(monkeypatch):
    monkeypatch.setenv("AGENT_WEB_FETCH_ENABLED", "false")
    assert (await tools._t_web_fetch({"url": "https://x.com"}, "b")).startswith("ERROR: web_fetch is disabled")


async def test_web_fetch_missing_url():
    assert (await tools._t_web_fetch({}, "b")).startswith("ERROR")
