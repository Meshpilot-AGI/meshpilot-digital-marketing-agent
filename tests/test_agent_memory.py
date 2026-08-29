"""AGENT-MEM — embeddings + store unit tests (no network, no DB)."""
from __future__ import annotations

import pytest

from glitch_signal.agent.memory import embeddings as emb
from glitch_signal.agent.memory import store
from glitch_signal.agent.memory.spec import Memory


# ── embeddings ────────────────────────────────────────────────────────
class _FakeHTTPResp:
    def __init__(self, status=200, payload=None, textbody=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = textbody

    def json(self):
        return self._payload


class _FakeHTTPClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._resp

    async def aclose(self):
        pass


async def test_embed_builds_request_and_orders_output(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    # response deliberately out of order → embed() must sort by index
    resp = _FakeHTTPResp(payload={"data": [
        {"index": 1, "embedding": [0.2, 0.2]},
        {"index": 0, "embedding": [0.1, 0.1]},
    ]})
    client = _FakeHTTPClient(resp)
    out = await emb.embed(["a", "b"], input_type="passage", client=client)
    assert out == [[0.1, 0.1], [0.2, 0.2]]
    body = client.calls[0]["json"]
    assert body["model"] == "nvidia/nemotron-3-embed-1b"
    assert body["input_type"] == "passage"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer nvapi-test"


async def test_embed_requires_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(emb.EmbeddingError, match="NVIDIA_API_KEY not set"):
        await emb.embed(["x"], client=_FakeHTTPClient(_FakeHTTPResp()))


async def test_embed_error_status(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    with pytest.raises(emb.EmbeddingError, match="-> 400"):
        await emb.embed(["x"], client=_FakeHTTPClient(_FakeHTTPResp(status=400, textbody="bad")))


def test_halfvec_literal():
    assert emb.to_halfvec_literal([0.5, -1.0, 2.0]) == "[0.5,-1.0,2.0]"


def test_embed_dim_matches_column():
    assert emb.EMBED_DIM == 2048  # keep in sync with halfvec(2048)


# ── store (fake engine) ───────────────────────────────────────────────
class _Result:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Row:
    """Mimics a SQLAlchemy Row with ._mapping."""
    def __init__(self, mapping):
        self._mapping = mapping


class _Conn:
    def __init__(self, engine):
        self.engine = engine

    async def execute(self, stmt, params=None):
        self.engine.calls.append((str(stmt), params or {}))
        return self.engine._results.pop(0) if self.engine._results else _Result()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeEngine:
    def __init__(self):
        self.calls = []
        self._results = []

    def queue(self, res):
        self._results.append(res)

    def begin(self):
        return _Conn(self)

    def connect(self):
        return _Conn(self)


async def _fake_embed(texts, input_type="passage"):
    return [[0.01] * emb.EMBED_DIM for _ in texts]


async def test_remember_fact_upserts_by_key():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("uuid-1", None)]))
    m = await store.remember("glitch_executor", "fact", "GE audience = prop traders",
                             key="audience", importance=0.9, embed_fn=_fake_embed, engine=eng)
    assert isinstance(m, Memory) and m.id == "uuid-1" and m.kind == "fact"
    sql, params = eng.calls[0]
    assert "ON CONFLICT" in sql  # fact + key → upsert
    assert params["kind"] == "fact" and params["key"] == "audience"
    assert params["emb"].startswith("[") and params["importance"] == 0.9


async def test_remember_episode_plain_insert():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("uuid-2", None)]))
    m = await store.remember("glitch_executor", "episode", "generated a logo",
                             embed_fn=_fake_embed, engine=eng)
    sql, params = eng.calls[0]
    assert "ON CONFLICT" not in sql  # no key → plain insert
    assert params["kind"] == "episode" and params["key"] is None and m.id == "uuid-2"


async def test_remember_bad_kind():
    with pytest.raises(ValueError, match="kind must be"):
        await store.remember("glitch_executor", "note", "x", embed_fn=_fake_embed, engine=FakeEngine())


async def test_remember_survives_embed_failure():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("uuid-3", None)]))

    async def boom(texts, input_type="passage"):
        raise RuntimeError("nvidia down")

    m = await store.remember("glitch_executor", "fact", "x", key="k", embed_fn=boom, engine=eng)
    assert m.id == "uuid-3"
    assert eng.calls[0][1]["emb"] is None  # stored with NULL embedding, still lexical


async def test_recall_hybrid_and_bumps_last_used():
    eng = FakeEngine()
    eng.queue(_Result(rows=[
        _Row({"id": "m1", "brand_id": "glitch_executor", "kind": "fact", "key": "audience",
              "content": "GE audience = prop traders", "metadata": {}, "importance": 0.9,
              "source": None, "created_at": None, "last_used_at": None,
              "semantic": 0.8, "lexical": 0.1, "score": 0.59}),
    ]))
    eng.queue(_Result(rowcount=1))  # the last_used_at UPDATE
    mems = await store.recall("glitch_executor", "who is GE for", k=5, embed_fn=_fake_embed, engine=eng)
    assert len(mems) == 1 and mems[0].id == "m1" and mems[0].score == pytest.approx(0.59)
    # recall SELECT then the UPDATE bump
    assert "SELECT" in eng.calls[0][0] and "agent_memory" in eng.calls[0][0]
    assert "UPDATE agent_memory SET last_used_at" in eng.calls[1][0]


async def test_recall_kind_filter():
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await store.recall("glitch_executor", "q", kinds=["fact", "bogus"], embed_fn=_fake_embed, engine=eng)
    sql, params = eng.calls[0]
    assert "string_to_array(:kinds_csv" in sql and params["kinds_csv"] == "fact"  # invalid kind filtered
