"""Internal control-surface — brand-scoped auth (#95 / BFLA).

`_require_jobs_auth` validates the x-jobs-token against the brand in the `?brand=` query param
(default brand when absent). These tests prove the body `brand` can NOT override that authorized
query brand on the remaining /internal|/jobs handlers that used to read `body.get("brand")`
(the PIPELINE endpoints were fixed earlier). A caller holding the default brand's token — or any
brand's token with no `?brand=` — must not be able to start actions for another brand by naming it
in the request body.

DB-touching calls (memory / run / cron stores) are monkeypatched, so these never hit a real
database. (This machine's local `.env` points at the real Supabase.)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "testtok"
H = {"x-jobs-token": TOKEN}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GE_JOBS_AUTH_TOKEN", TOKEN)   # jobs-auth for the default brand (glitch_executor)
    import glitch_signal.server as srv
    return TestClient(srv.app)


# ── /internal/agent/remember — a memory WRITE must land on the authorized brand only ──
class _FakeMem:
    id, kind, key = "m1", "fact", None


def _patch_remember(monkeypatch, captured):
    async def _fake_remember(brand, kind, content, **kw):
        captured["brand"] = brand
        return _FakeMem()

    monkeypatch.setattr("glitch_signal.agent.memory.remember", _fake_remember)


def test_remember_body_brand_cannot_override_default(client, monkeypatch):
    """No ?brand= (authorized = default) + a smuggled body brand → 400, nothing written."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember", headers=H,
                    json={"brand": "someone_else", "kind": "fact", "content": "x"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # remember() never ran → no cross-brand write


def test_remember_body_brand_cannot_override_query(client, monkeypatch):
    """?brand=glitch_executor + a differing body brand → 400, nothing written."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember?brand=glitch_executor", headers=H,
                    json={"brand": "someone_else", "kind": "fact", "content": "x"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured


def test_remember_writes_authorized_brand(client, monkeypatch):
    """No brand in body → the authorized (default) brand is used — behavior unchanged."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember", headers=H,
                    json={"kind": "fact", "content": "x"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"


def test_remember_matching_body_brand_ok(client, monkeypatch):
    """A body brand equal to the authorized query brand is accepted (no false 400)."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember?brand=glitch_executor", headers=H,
                    json={"brand": "glitch_executor", "kind": "fact", "content": "x"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"


# ── /internal/agent/run — starting an agent loop must target the authorized brand only ──
def _patch_run(monkeypatch, captured):
    async def _fake_create_run(run_id, brand, goal):
        captured["brand"] = brand

    async def _fake_bg(*a, **k):
        return None

    monkeypatch.setattr("glitch_signal.agent.loop.runs.create_run", _fake_create_run)
    monkeypatch.setattr("glitch_signal.server._run_agent_bg", _fake_bg)


def test_run_body_brand_cannot_override(client, monkeypatch):
    captured: dict = {}
    _patch_run(monkeypatch, captured)
    r = client.post("/internal/agent/run", headers=H,
                    json={"brand": "someone_else", "goal": "do a thing"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # the background run never started


def test_run_uses_authorized_brand(client, monkeypatch):
    captured: dict = {}
    _patch_run(monkeypatch, captured)
    r = client.post("/internal/agent/run", headers=H, json={"goal": "do a thing"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"


# ── /internal/cron/jobs — persistent state (a scheduled job) must be brand-scoped too ──
def test_cron_create_body_brand_cannot_override(client, monkeypatch):
    captured: dict = {}

    async def _fake_create_job(**kw):
        captured["brand"] = kw.get("brand_id")
        return "job1"

    monkeypatch.setattr("glitch_signal.agent.cron.store.create_job", _fake_create_job)
    r = client.post("/internal/cron/jobs", headers=H, json={
        "brand": "someone_else", "name": "j", "schedule_kind": "every",
        "schedule": {"every_ms": 1000}, "payload_kind": "agentTurn",
    })
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # no job created against another brand


# ── /internal/{facebook,instagram}/test-post — publishing target is the AUTHORIZED brand, not the
#    body `brand_id` (the field these two use). Closes the BFLA the sibling sweep missed. ──
def _patch_fb(monkeypatch, captured):
    async def _fake(**kw):
        captured["brand"] = kw.get("brand_id")
        return ("pid", "https://fb/permalink")
    monkeypatch.setattr("glitch_signal.platforms.facebook.publish_facebook", _fake)


def _patch_ig(monkeypatch, captured):
    async def _fake(**kw):
        captured["brand"] = kw.get("brand_id")
        return ("mid", "https://ig/permalink")
    monkeypatch.setattr("glitch_signal.platforms.instagram.publish_instagram", _fake)


def test_facebook_body_brand_id_cannot_override(client, monkeypatch):
    captured: dict = {}
    _patch_fb(monkeypatch, captured)
    r = client.post("/internal/facebook/test-post?brand=glitch_executor", headers=H,
                    json={"brand_id": "someone_else", "message": "hi"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # never published as another brand


def test_facebook_publishes_as_authorized_brand(client, monkeypatch):
    captured: dict = {}
    _patch_fb(monkeypatch, captured)
    r = client.post("/internal/facebook/test-post?brand=glitch_executor", headers=H,
                    json={"message": "hi"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"       # target = authorized brand, not body


def test_instagram_body_brand_id_cannot_override(client, monkeypatch):
    captured: dict = {}
    _patch_ig(monkeypatch, captured)
    r = client.post("/internal/instagram/test-post?brand=glitch_executor", headers=H,
                    json={"brand_id": "someone_else", "image_url": "https://x/y.png"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured


# ── #2: the no-query default is settings().default_brand_id, not a hardcoded "glitch_executor" ──
def test_authorized_brand_uses_configured_default(monkeypatch):
    from types import SimpleNamespace

    import glitch_signal.server as srv

    monkeypatch.setattr(srv, "settings", lambda: SimpleNamespace(default_brand_id="other_brand"))
    monkeypatch.setattr(srv, "brand_ids", lambda: ["glitch_executor", "other_brand"])
    req = SimpleNamespace(query_params={})               # no ?brand=
    assert srv._authorized_brand(req) == "other_brand"   # authenticated default, not the literal


# ── #197 follow-up: the PATH brand must not bypass the authorized brand either ──────────────
#
# `_require_jobs_auth` validates the token against `?brand=` (default brand when absent), but the
# /internal/brand/{brand_id}/documents handlers then acted on the PATH segment with no cross-check.
# Same BFLA shape as the body-brand hole #95 closed — it just arrived through the URL instead.
def _patch_docs(monkeypatch, captured):
    async def _list(brand):
        captured["list"] = brand
        return []

    async def _add(brand, *a, **k):
        captured["add"] = brand
        return {"id": "d1", "filename": "f.txt"}

    async def _delete(brand, doc_id):
        captured["delete"] = brand
        return "file-1"

    async def _upload_file(data, name, mime):
        return {"id": "file-1", "filename": name, "mime_type": mime, "size_bytes": len(data)}

    async def _delete_file(file_id):
        captured["file_deleted"] = file_id

    monkeypatch.setattr("glitch_signal.agent.documents.list_for_brand", _list)
    monkeypatch.setattr("glitch_signal.agent.documents.add", _add)
    monkeypatch.setattr("glitch_signal.agent.documents.delete", _delete)
    monkeypatch.setattr("glitch_signal.agent.files.upload_file", _upload_file)
    monkeypatch.setattr("glitch_signal.agent.files.delete_file", _delete_file)


def test_document_list_path_brand_cannot_override_default(client, monkeypatch):
    """The default brand's token + another brand in the PATH → 403, nothing read."""
    captured: dict = {}
    _patch_docs(monkeypatch, captured)
    r = client.get("/internal/brand/someone_else/documents", headers=H)
    assert r.status_code == 403, r.text
    assert "list" not in captured                       # the handler never reached the store


def test_document_list_path_brand_cannot_override_query(client, monkeypatch):
    """?brand=glitch_executor + a differing PATH brand → 403, nothing read."""
    captured: dict = {}
    _patch_docs(monkeypatch, captured)
    r = client.get("/internal/brand/someone_else/documents?brand=glitch_executor", headers=H)
    assert r.status_code == 403, r.text
    assert "list" not in captured


def test_document_list_allows_the_authorized_brand(client, monkeypatch):
    """The fix must not break the legitimate single-brand call."""
    captured: dict = {}
    _patch_docs(monkeypatch, captured)
    r = client.get("/internal/brand/glitch_executor/documents?brand=glitch_executor", headers=H)
    assert r.status_code == 200, r.text
    assert captured["list"] == "glitch_executor"


def test_document_delete_path_brand_cannot_override(client, monkeypatch):
    """A cross-brand DELETE is the most damaging of the three — it must not reach the store."""
    captured: dict = {}
    _patch_docs(monkeypatch, captured)
    r = client.delete("/internal/brand/someone_else/documents/doc-1", headers=H)
    assert r.status_code == 403, r.text
    assert "delete" not in captured and "file_deleted" not in captured


def test_document_upload_path_brand_cannot_override(client, monkeypatch):
    """A cross-brand upload would plant a document the OTHER brand's agent then treats as ground
    truth via read_brand_doc — grounding poisoning, not just data leakage."""
    captured: dict = {}
    _patch_docs(monkeypatch, captured)
    r = client.post("/internal/brand/someone_else/documents", headers=H,
                    files={"file": ("f.txt", b"hello", "text/plain")})
    assert r.status_code == 403, r.text
    assert "add" not in captured


def test_unknown_path_brand_is_still_rejected(client, monkeypatch):
    """A nonexistent brand must not 500 its way through — it simply isn't the authorized brand."""
    captured: dict = {}
    _patch_docs(monkeypatch, captured)
    r = client.get("/internal/brand/no_such_brand/documents", headers=H)
    assert r.status_code == 403, r.text
    assert "list" not in captured
