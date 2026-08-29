"""AGENT-LEARN — Hermes-style curator: distill episodes -> durable lessons (no network/DB)."""
from __future__ import annotations

from glitch_signal.agent.learn import curator


# ── lesson parsing ────────────────────────────────────────────────────
def test_parse_lessons_clean():
    raw = '[{"key":"a","content":"x","importance":0.8}]'
    out = curator._parse_lessons(raw)
    assert out == [{"key": "a", "content": "x", "importance": 0.8}]


def test_parse_lessons_wrapped_in_prose():
    raw = 'Here are the lessons:\n```json\n[{"key":"k","content":"c"}]\n```\nDone.'
    assert curator._parse_lessons(raw) == [{"key": "k", "content": "c"}]


def test_parse_lessons_garbage_returns_empty():
    assert curator._parse_lessons("no json here") == []


def test_slug_is_stable_and_safe():
    a = curator._slug("Post CTAs Convert Better")
    b = curator._slug("Post CTAs Convert Better")
    assert a == b and " " not in a and a == a.lower()


# ── curate() orchestration (all deps injected) ────────────────────────
class _LLM:
    def __init__(self, resp):
        self.resp = resp
        self.calls = 0

    async def __call__(self, prompt, *, system=None):
        self.calls += 1
        return self.resp


async def test_curate_no_episodes_is_noop():
    llm = _LLM("[]")
    remembered = []
    res = await curator.curate(
        "b", llm=llm, remember_fn=lambda *a, **k: remembered.append(a),
        fetch_fn=lambda brand, limit: _aval([]), mark_fn=lambda ids: _aval(None),
    )
    assert res == {"episodes": 0, "lessons": 0}
    assert llm.calls == 0 and remembered == []          # no episodes -> LLM never called


async def test_curate_distills_and_marks():
    eps = [("id1", "did X and it worked"), ("id2", "tried Y, failed")]
    llm = _LLM('[{"key":"x-works","content":"X works for this brand","importance":0.9},'
               '{"key":"avoid-y","content":"Avoid Y","importance":0.6}]')
    remembered, marked = [], []

    async def fake_remember(brand, kind, content, *, key=None, importance=0.5, source=None, **kw):
        remembered.append({"kind": kind, "content": content, "key": key,
                           "importance": importance, "source": source})

    res = await curator.curate(
        "glitch_executor", llm=llm, remember_fn=fake_remember,
        fetch_fn=lambda brand, limit: _aval(eps),
        mark_fn=lambda ids: _aval(marked.extend(ids)),
    )
    assert res == {"episodes": 2, "lessons": 2}
    assert all(r["kind"] == "fact" and r["source"] == "curator" for r in remembered)
    assert remembered[0]["key"].startswith("lesson:")
    assert marked == ["id1", "id2"]                     # processed episodes marked curated


async def test_curate_skips_empty_lesson_content():
    eps = [("id1", "ep")]
    llm = _LLM('[{"key":"k","content":""},{"key":"k2","content":"real lesson"}]')
    remembered = []

    async def fake_remember(brand, kind, content, *, key=None, **kw):
        remembered.append(content)

    res = await curator.curate(
        "b", llm=llm, remember_fn=fake_remember,
        fetch_fn=lambda brand, limit: _aval(eps), mark_fn=lambda ids: _aval(None),
    )
    assert res["lessons"] == 1 and remembered == ["real lesson"]  # empty one skipped


# tiny async-value helper for injected coroutines
async def _aval(v):
    return v
