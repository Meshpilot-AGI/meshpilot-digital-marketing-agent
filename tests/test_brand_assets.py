"""Brand asset library — real files the pipeline composites, never generates.

An image model cannot render a third-party mark; asked for the FTMO logo it produces a mangled
approximation that both looks wrong and misrepresents a real trademark. So these are stored files.
"""
import json

import pytest

from glitch_signal.agent import assets
from tests.test_agent_memory import FakeEngine, _Result, _Row


async def test_register_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        await assets.register("ge", kind="hologram", slug="x", name="X", url="u",
                              engine=FakeEngine())


async def test_register_upserts_on_owner_kind_slug():
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    await assets.register("ge", kind="logo", slug="ftmo", name="FTMO", url="u", engine=eng)
    sql, params = eng.calls[0]
    assert "on conflict (owner_brand, kind, slug) do update" in sql.lower()
    assert params["o"] == "ge" and params["s"] == "ftmo"


# ── reproducible handle writes (finding: "Verified handles never populated") ───────────────────────
async def test_register_can_write_verified_handles():
    """Before this, `register` had no `handles` parameter at all, so the only way a value ever
    reached `brand_asset.handles` was an out-of-repository manual database edit — unreproducible on
    a fresh environment and invisible to any migration or code review."""
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    await assets.register("ge", kind="logo", slug="ftmo", name="FTMO", url="u",
                          handles={"x": "@FTMO_com"}, engine=eng)
    sql, params = eng.calls[0]
    assert "handles" in sql.lower()
    assert json.loads(params["handles"]) == {"x": "@FTMO_com"}


async def test_register_leaves_handles_untouched_when_not_supplied():
    """A caller updating unrelated asset fields (a new logo URL, say) must never accidentally wipe
    verified handles it does not know about by omitting them."""
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    await assets.register("ge", kind="logo", slug="ftmo", name="FTMO", url="u", engine=eng)
    sql, params = eng.calls[0]
    assert "handles" not in params


async def test_find_is_scoped_to_the_owner_brand():
    """A tenant's library must never leak into another's creative."""
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await assets.find("ge", kind="logo", engine=eng)
    _sql, params = eng.calls[0]
    assert params["o"] == "ge" and params["k"] == "logo"


async def test_find_degrades_to_empty_on_db_failure():
    """A missing library must mean 'no imagery', not a failed campaign."""
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")
    assert await assets.find("ge", engine=_Boom()) == []


def _lib():
    return [{"slug": "ftmo", "name": "FTMO", "kind": "logo", "url": "u1",
             "width": 256, "height": 256, "accent": None, "usage_note": None},
            {"slug": "apex", "name": "Apex Trader Funding", "kind": "logo", "url": "u2",
             "width": 256, "height": 256, "accent": None, "usage_note": None}]


async def test_resolve_named_matches_what_the_agent_actually_wrote(monkeypatch):
    """The agent writes firm NAMES in copy, not slugs, so the lookup has to meet it there."""
    async def _find(owner, *, kind=None, slug=None, engine=None):
        return _lib()
    monkeypatch.setattr(assets, "find", _find)
    got = await assets.resolve_named("ge", ["FTMO", "apex"])
    assert [g["slug"] for g in got] == ["ftmo", "apex"]


async def test_resolve_named_matches_a_partial_display_name(monkeypatch):
    """'Apex' must find 'Apex Trader Funding' — copy rarely uses the full legal name."""
    async def _find(owner, *, kind=None, slug=None, engine=None):
        return _lib()
    monkeypatch.setattr(assets, "find", _find)
    assert [g["slug"] for g in await assets.resolve_named("ge", ["Apex"])] == ["apex"]


async def test_resolve_named_drops_unknown_names(monkeypatch):
    """A post naming a firm we hold no mark for still renders — just without that logo."""
    async def _find(owner, *, kind=None, slug=None, engine=None):
        return _lib()
    monkeypatch.setattr(assets, "find", _find)
    got = await assets.resolve_named("ge", ["FTMO", "Definitely Not A Firm", ""])
    assert [g["slug"] for g in got] == ["ftmo"]


async def test_resolve_named_does_not_duplicate(monkeypatch):
    async def _find(owner, *, kind=None, slug=None, engine=None):
        return _lib()
    monkeypatch.setattr(assets, "find", _find)
    assert len(await assets.resolve_named("ge", ["FTMO", "ftmo", "FTMO"])) == 1
