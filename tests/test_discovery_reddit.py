"""TARGET-1 — Reddit sensing: client shape, gating, brand-neutrality, and the observation store."""
from __future__ import annotations

import json

import pytest

from glitch_signal.agent.discovery import reddit, store


def _mock(monkeypatch, payload, capture=None):
    """Serve `payload` to the client's httpx call, recording the request if asked."""
    import httpx

    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["url"] = str(request.url)
        return httpx.Response(200, json=payload)

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setenv("REDDITAPIS_TOKEN", "test-token")


# ── client ──
async def test_search_posts_compacts_to_what_a_decision_needs(monkeypatch):
    _mock(monkeypatch, {"posts": [{
        "id": "abc", "subreddit": "propfirm", "title": "T", "text": "x" * 900,
        "author": "someone", "upvotes": 12, "num_comments": 3, "permalink": "/r/propfirm/abc",
        "thumbnail": "junk", "preview": {"lots": "of noise"},
    }], "after": "t3_abc"})
    out = await reddit.search_posts("drawdown")
    p = out["posts"][0]
    assert p["subreddit"] == "propfirm" and p["upvotes"] == 12
    assert len(p["excerpt"]) <= 400          # the loop pays per token; body is trimmed
    assert "thumbnail" not in p and "preview" not in p
    assert out["after"] == "t3_abc"          # paging without re-running the query


async def test_search_posts_defaults_to_relevance(monkeypatch):
    """`top` returns all-time global posts and `new` returns whatever is recent — both nearly ignore
    the query (measured live 2026-09-02). Relevance is the only sort that targets."""
    cap = {}
    _mock(monkeypatch, {"posts": []}, capture=cap)
    await reddit.search_posts("prop firm rules")
    assert "sort=relevance" in cap["url"]


async def test_search_communities_keeps_subscriber_counts(monkeypatch):
    """Subscriber count is the first input to scoring a surface — a room's size bounds its reach."""
    _mock(monkeypatch, {"communities": [{"name": "propfirm", "subscribers": 39229, "title": "t"}]})
    out = await reddit.search_communities("prop firm")
    assert out["communities"][0]["subscribers"] == 39229


async def test_limit_is_clamped(monkeypatch):
    cap = {}
    _mock(monkeypatch, {"posts": []}, capture=cap)
    await reddit.search_posts("q", limit=9999)
    assert "limit=100" in cap["url"]


async def test_missing_token_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("REDDITAPIS_TOKEN", raising=False)
    monkeypatch.setattr("glitch_signal.config.settings", lambda: type("S", (), {"redditapis_token": ""})())
    with pytest.raises(RuntimeError, match="REDDITAPIS_TOKEN"):
        await reddit.search_posts("q")


def test_client_names_no_industry_or_brand():
    """Multi-brand guard: the sensing layer must not know what business it is in.

    Queries come from the caller (ultimately the brand's declared audience), so a second brand
    discovers entirely different rooms with the same code. Docstrings may cite the measured GE
    examples as evidence; EXECUTABLE code may not — so docstrings are stripped via the AST rather
    than by guessing at line prefixes.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(reddit))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:]
    # `glitch_signal` is this package's own namespace, not a brand reference — strip it before
    # checking, or every import looks like brand leakage.
    code = ast.unparse(tree).lower().replace("glitch_signal", "")
    for term in ("propfirm", "prop firm", "trading", "glitchexecutor", "glitch_executor", "drawdown"):
        assert term not in code, f"sensing code hardcodes {term!r}"


# ── gating ──
def test_discovery_tools_are_policy_gated():
    """Ships inert: external, paid pulls stay off until `agent_discovery_enabled` is flipped."""
    from glitch_signal.agent.loop import policy

    assert "discover_conversations" in policy.DISCOVERY_TOOLS
    assert "discover_communities" in policy.DISCOVERY_TOOLS


def test_discovery_scope_offers_them_but_chat_does_not():
    from glitch_signal.agent.loop import scopes

    assert scopes.resolve("discovery").allows("discover_conversations")
    assert not scopes.resolve("chat").allows("discover_conversations")


def test_tools_are_registered_with_query_required():
    from glitch_signal.agent.loop.tools import TOOLS

    for name in ("discover_conversations", "discover_communities"):
        assert name in TOOLS
        assert "query" in TOOLS[name]["input_schema"]["required"]


# ── store ──
class _Conn:
    def __init__(self, sink, rows):
        self._sink, self._rows = sink, rows

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _Res(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Engine:
    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    def begin(self):
        return _Conn(self.calls, self._rows)

    def connect(self):
        return _Conn(self.calls, self._rows)


async def test_record_upserts_so_reobserving_does_not_duplicate():
    eng = _Engine()
    n = await store.record("b", "reddit", "post",
                           [{"id": "abc", "subreddit": "x", "title": "t", "upvotes": 5}],
                           query="q", engine=eng)
    assert n == 1
    sql, params = eng.calls[0]
    assert "on conflict (brand_id, source, external_id) do update" in sql.lower()
    assert params["external_id"] == "abc" and params["query"] == "q"
    json.loads(params["raw"])            # raw must be valid json for the jsonb cast


async def test_record_skips_items_with_no_id():
    """Nothing to dedup on — writing it would create a row that can never be matched again."""
    eng = _Engine()
    await store.record("b", "reddit", "post", [{"title": "no id here"}], engine=eng)
    assert eng.calls == []


async def test_record_never_raises_into_the_caller():
    class _Boom:
        def begin(self):
            raise RuntimeError("db down")

    assert await store.record("b", "reddit", "post", [{"id": "a"}], engine=_Boom()) == 0


async def test_seen_ids_fails_open():
    """A lookup failure should re-surface something already seen, never hide something new."""
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")

    assert await store.seen_ids("b", "reddit", ["a"], engine=_Boom()) == set()


async def test_seen_ids_short_circuits_on_empty():
    eng = _Engine()
    assert await store.seen_ids("b", "reddit", [], engine=eng) == set()
    assert eng.calls == []               # no pointless round-trip
