"""FILES lane — Files API client, brand_document store isolation, read_brand_doc tool."""
from __future__ import annotations

import pytest

from glitch_signal.agent import documents, files
from glitch_signal.agent.loop import llm as loop_llm
from glitch_signal.agent.loop import tools


# ── Files API client ──────────────────────────────────────────────────
class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.text = str(payload)

    def json(self):
        return self._p


class _FilesClient:
    def __init__(self, resp):
        self._resp = resp
        self.posted = None
        self.deleted = None

    async def post(self, url, *, headers=None, files=None):
        self.posted = {"url": url, "files": files}
        return self._resp

    async def delete(self, url, *, headers=None):
        self.deleted = url
        return self._resp


async def test_upload_file_posts_multipart(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _FilesClient(_Resp(200, {"id": "file_abc", "filename": "g.txt",
                                 "mime_type": "text/plain", "size_bytes": 5}))
    rec = await files.upload_file(b"hello", "g.txt", "text/plain", client=c)
    assert rec["id"] == "file_abc"
    assert c.posted["url"].endswith("/v1/files")
    assert c.posted["files"]["file"][0] == "g.txt"       # (filename, data, mime)


async def test_upload_file_raises_on_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _FilesClient(_Resp(400, {"error": "bad"}))
    with pytest.raises(RuntimeError):
        await files.upload_file(b"x", "f", "text/plain", client=c)


async def test_delete_file(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-x")
    c = _FilesClient(_Resp(200, {}))
    assert await files.delete_file("file_abc", client=c) is True
    assert c.deleted.endswith("/v1/files/file_abc")


# ── documents store (fake engine, brand isolation) ────────────────────
class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def first(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Conn:
    def __init__(self, engine):
        self.engine = engine

    async def execute(self, stmt, params=None):
        self.engine.calls.append((str(stmt), params or {}))
        return self.engine._results.pop(0) if self.engine._results else _Result()

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


async def test_documents_add_scopes_brand():
    eng = FakeEngine()
    eng.queue(_Result([("00000000-0000-0000-0000-000000000001", "2026-08-30")]))
    row = await documents.add("brand_a", "file_1", "guide.pdf",
                              mime_type="application/pdf", size_bytes=10, engine=eng)
    assert row["file_id"] == "file_1" and row["brand_id"] == "brand_a"
    sql, params = eng.calls[0]
    assert "INSERT INTO brand_document" in sql and params["brand"] == "brand_a"


async def test_documents_list_is_brand_scoped():
    eng = FakeEngine()
    eng.queue(_Result([{"id": "id1", "file_id": "file_1", "filename": "g.pdf",
                        "mime_type": "application/pdf", "size_bytes": 10, "kind": "doc",
                        "created_at": None}]))
    docs = await documents.list_for_brand("brand_a", engine=eng)
    assert docs[0]["file_id"] == "file_1" and docs[0]["id"] == "id1"
    sql, params = eng.calls[0]
    assert "WHERE brand_id = :brand" in sql and params["brand"] == "brand_a"   # isolation


async def test_documents_delete_is_brand_scoped():
    eng = FakeEngine()
    eng.queue(_Result([("file_1",)]))
    fid = await documents.delete("brand_a", "id1", engine=eng)
    assert fid == "file_1"
    sql, params = eng.calls[0]
    assert "brand_id = :brand" in sql and params == {"brand": "brand_a", "id": "id1"}


# ── read_brand_doc tool ───────────────────────────────────────────────
async def test_read_brand_doc_no_docs(monkeypatch):
    async def _empty(brand_id, **k):
        return []
    monkeypatch.setattr("glitch_signal.agent.documents.list_for_brand", _empty)
    out = await tools._t_read_brand_doc({"query": "tone?"}, "brand_a")
    assert "No brand documents" in out


async def test_read_brand_doc_builds_document_blocks(monkeypatch):
    async def _docs(brand_id, **k):
        return [{"file_id": "file_1"}, {"file_id": "file_2"}]

    captured = {}

    async def _fake_complete(messages, **k):
        captured["messages"] = messages
        return "the tone is sharp"

    monkeypatch.setattr("glitch_signal.agent.documents.list_for_brand", _docs)
    monkeypatch.setattr(loop_llm, "complete_messages", _fake_complete)
    out = await tools._t_read_brand_doc({"query": "what tone?"}, "brand_a")
    assert out == "the tone is sharp"
    blocks = captured["messages"][-1]["content"]
    docblocks = [b for b in blocks if b.get("type") == "document"]
    assert {b["source"]["file_id"] for b in docblocks} == {"file_1", "file_2"}
    assert blocks[-1]["type"] == "text"                  # query appended after the docs


# ── document block passthrough in the OpenAI→Anthropic conversion ──────
def test_content_to_anthropic_passes_document_blocks():
    doc = {"type": "document", "source": {"type": "file", "file_id": "file_1"}}
    out = loop_llm._content_to_anthropic([doc, {"type": "text", "text": "q"}])
    assert out[0] == doc                                 # passed through, not stringified
    assert out[1] == {"type": "text", "text": "q"}
