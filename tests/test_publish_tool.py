"""Agent publish tool → Buffer create_post, with the pre-publish conscience gate."""
from __future__ import annotations

import glitch_signal.agent.loop.tools as tools


def _proxy_conscience(monkeypatch, enabled: bool):
    from glitch_signal.config import settings as _s
    real = _s()

    class _O:
        def __getattr__(self, k):
            return enabled if k == "agent_conscience_enabled" else getattr(real, k)

    monkeypatch.setattr("glitch_signal.config.settings", lambda: _O())


async def test_publish_missing_fields():
    assert (await tools._t_publish({"platform": "x"}, "b")).startswith("ERROR")
    assert (await tools._t_publish({"text": "hi"}, "b")).startswith("ERROR")


async def test_publish_posts_via_buffer(monkeypatch):
    _proxy_conscience(monkeypatch, False)          # conscience off → no pre-publish gate
    calls: dict = {}

    async def _cp(brand_id, service, *, text, media_url=None, mode="shareNow"):
        calls.update(brand=brand_id, service=service, text=text, mode=mode)
        return ("bp1", "sending")

    monkeypatch.setattr("glitch_signal.platforms.buffer.create_post", _cp)
    out = await tools._t_publish({"platform": "x", "text": "GE launched!"}, "glitch_executor")
    assert "PUBLISHED to x" in out and "bp1" in out
    assert calls["service"] == "x" and calls["mode"] == "shareNow" and calls["text"] == "GE launched!"


async def test_publish_failsoft_on_buffer_error(monkeypatch):
    _proxy_conscience(monkeypatch, False)

    async def _boom(*a, **k):
        raise RuntimeError("buffer down")

    monkeypatch.setattr("glitch_signal.platforms.buffer.create_post", _boom)
    out = await tools._t_publish({"platform": "x", "text": "hi"}, "b")
    assert out.startswith("ERROR") and "buffer down" in out


async def test_publish_blocked_by_conscience_escalate(monkeypatch):
    _proxy_conscience(monkeypatch, True)
    posted = {"n": 0}

    async def _cp(*a, **k):
        posted["n"] += 1
        return ("x", "y")

    async def _rev(goal, output, **k):
        return {"verdict": "escalate", "notes": "misleading claim"}

    monkeypatch.setattr("glitch_signal.platforms.buffer.create_post", _cp)
    monkeypatch.setattr("glitch_signal.agent.loop.conscience.review", _rev)
    out = await tools._t_publish({"platform": "x", "text": "guaranteed 500% returns"}, "b")
    assert out.startswith("BLOCKED by conscience") and posted["n"] == 0   # never posted


async def test_publish_conscience_concerns_still_posts(monkeypatch):
    _proxy_conscience(monkeypatch, True)

    async def _cp(*a, **k):
        return ("bp2", "sending")

    async def _rev(goal, output, **k):
        return {"verdict": "concerns", "notes": "tone"}

    monkeypatch.setattr("glitch_signal.platforms.buffer.create_post", _cp)
    monkeypatch.setattr("glitch_signal.agent.loop.conscience.review", _rev)
    out = await tools._t_publish({"platform": "x", "text": "hello"}, "b")
    assert "PUBLISHED" in out                                # concerns is advisory; only escalate blocks
