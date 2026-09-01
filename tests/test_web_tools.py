"""web_search / web_fetch client tools — OpenRouter-backed, gated, SSRF-guarded (no network)."""
from __future__ import annotations

import json

import glitch_signal.agent.loop.tools as tools
from glitch_signal.agent.loop.policy import Policy


# ── web_search ────────────────────────────────────────────────────────
async def test_web_search_calls_openrouter_web(monkeypatch):
    async def _cw(query, *, max_results=5, **k):
        return ("GE is a prop-firm trading platform", ["https://glitchexecutor.com"])

    monkeypatch.setattr("glitch_signal.agent.loop.llm.complete_web", _cw)
    out = await tools._t_web_search({"query": "what is GE"}, "b")
    d = json.loads(out)
    assert "trading platform" in d["answer"] and d["sources"] == ["https://glitchexecutor.com"]


def test_web_search_disabled_by_default_via_policy():
    # web_search has no in-tool kill-switch (#191) — the policy gate is the ONLY enforcement point,
    # and it denies by default (mirrors send_email/discover_trending: safe-off until deliberately on).
    d = Policy().check("web_search", {}, "b")
    assert d.allow is False and "disabled" in d.reason


async def test_web_search_missing_query():
    assert (await tools._t_web_search({}, "b")).startswith("ERROR")


# ── SSRF guard ────────────────────────────────────────────────────────
def test_web_url_precheck_rejects_scheme_and_literal_ips():
    assert tools._web_url_precheck("ftp://example.com")[0] is False        # scheme
    assert tools._web_url_precheck("file:///etc/passwd")[0] is False
    assert tools._web_url_precheck("http://127.0.0.1/x")[0] is False       # loopback (literal IP)
    assert tools._web_url_precheck("http://169.254.169.254/latest/meta-data")[0] is False  # metadata (link-local)
    assert tools._web_url_precheck("http://[::1]/x")[0] is False           # IPv6 loopback
    ok, _why, host, port = tools._web_url_precheck("https://example.com/path")
    assert ok is True and host == "example.com" and port == 443           # public hostname passes the sync pre-check


def test_web_url_precheck_blocked_domain(monkeypatch):
    monkeypatch.setenv("AGENT_WEB_BLOCKED_DOMAINS", "evil.com, spam.io")
    assert tools._web_url_precheck("https://evil.com/x")[0] is False
    assert tools._web_url_precheck("https://sub.evil.com/x")[0] is False   # subdomain of a blocked domain
    assert tools._web_url_precheck("https://EVIL.com/x")[0] is False       # case-insensitive
    assert tools._web_url_precheck("https://evil.com./x")[0] is False      # trailing-dot FQDN must not bypass


def test_canonical_host_normalizes_dot_and_case():
    assert tools._canonical_host("Example.COM.") == "example.com"          # lowercase + strip root dot


async def test_web_url_resolve_rejects_private_dns_rebinding(monkeypatch):
    # A hostname that resolves to a private/metadata IP must be refused — closes the rebinding window
    # by validating the resolved address (the caller then pins the connection to it).
    import asyncio

    async def _fake_getaddrinfo(host, port, **k):
        return [(2, 1, 6, "", ("169.254.169.254", port))]      # link-local (cloud metadata)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_getaddrinfo)
    ok, why, *_ = await tools._web_url_resolve("http://rebind.example/x")
    assert ok is False and "non-public" in why


async def test_web_url_resolve_binds_validated_public_ip(monkeypatch):
    import asyncio

    async def _fake_getaddrinfo(host, port, **k):
        return [(2, 1, 6, "", ("93.184.216.34", port))]        # example.com, public

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_getaddrinfo)
    ok, why, host, ip, port = await tools._web_url_resolve("https://example.com/path")
    assert ok is True and host == "example.com" and ip == "93.184.216.34" and port == 443


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


async def _resolve_ok(url):
    return (True, "", "x.com", "93.184.216.34", 443)          # stub: guard passed, connection pins to this IP


async def test_web_fetch_strips_html(monkeypatch):
    monkeypatch.setattr(tools, "_web_url_resolve", _resolve_ok)
    monkeypatch.setattr("httpx.AsyncClient",
                        lambda **k: _StreamClient(200, b"<html><style>x{}</style><body>Hello <b>world</b></body></html>"))
    out = await tools._t_web_fetch({"url": "https://x.com"}, "b")
    assert "Hello world" in out and "<b>" not in out and "x{}" not in out


async def test_web_fetch_rejects_redirect(monkeypatch):
    monkeypatch.setattr(tools, "_web_url_resolve", _resolve_ok)
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _StreamClient(302, b""))
    assert (await tools._t_web_fetch({"url": "https://x.com"}, "b")).startswith("ERROR: web_fetch got a redirect")


async def test_web_fetch_http_error_not_returned_as_text(monkeypatch):
    monkeypatch.setattr(tools, "_web_url_resolve", _resolve_ok)
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _StreamClient(500, b"<html>error page</html>"))
    out = await tools._t_web_fetch({"url": "https://x.com"}, "b")
    assert out.startswith("ERROR: web_fetch got HTTP 500") and "error page" not in out


async def test_web_fetch_hard_byte_cap(monkeypatch):
    # The cap must bound RETAINED bytes: only the remaining allowance of an oversized chunk is kept.
    monkeypatch.setattr(tools, "_web_url_resolve", _resolve_ok)
    monkeypatch.setattr(tools, "_WEB_FETCH_MAX_BYTES", 10)
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _StreamClient(200, b"AAAAAAAAAA" + b"B" * 1_000_000))
    out = await tools._t_web_fetch({"url": "https://x.com"}, "b")
    assert out == "AAAAAAAAAA" and "B" not in out             # kept exactly 10 bytes, not the whole 1MB chunk


async def test_web_fetch_refused_on_ssrf():
    assert (await tools._t_web_fetch({"url": "http://127.0.0.1/x"}, "b")).startswith("ERROR: web_fetch refused")


def test_web_fetch_disabled_by_default_via_policy():
    # web_fetch has no in-tool kill-switch (#191) — the policy gate is the ONLY enforcement point,
    # and it denies by default (mirrors send_email/discover_trending: safe-off until deliberately on).
    d = Policy().check("web_fetch", {}, "b")
    assert d.allow is False and "disabled" in d.reason


async def test_web_fetch_missing_url():
    assert (await tools._t_web_fetch({}, "b")).startswith("ERROR")
