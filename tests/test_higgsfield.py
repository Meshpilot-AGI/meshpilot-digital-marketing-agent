"""Higgsfield engine — SDK wrapped behind the Engine protocol (mock client, no network)."""
from __future__ import annotations

import pytest

from glitch_signal.media.generation.engines.higgsfield import HiggsfieldEngine, _extract_url


def test_extract_url_from_images():
    assert _extract_url({"images": [{"url": "https://cdn/i.png"}]}) == "https://cdn/i.png"


def test_extract_url_from_video_object():
    assert _extract_url({"video": {"url": "https://cdn/v.mp4"}}) == "https://cdn/v.mp4"


def test_extract_url_raises_when_absent():
    from glitch_signal.media.generation.engines.base import EngineError
    with pytest.raises(EngineError):
        _extract_url({"status": "ok"})


class _FakeClient:
    def __init__(self):
        self.call = None

    async def subscribe(self, application, arguments):
        self.call = {"application": application, "arguments": arguments}
        return {"images": [{"url": "https://cdn/out.png"}]}


async def test_generate_calls_subscribe_and_extracts_url():
    fake = _FakeClient()
    eng = HiggsfieldEngine(client_factory=lambda: fake)
    url = await eng.generate("some/app/text-to-image", "a red cube",
                             params={"resolution": "1K"}, images=["https://ref/x.png"])
    assert url == "https://cdn/out.png"
    assert fake.call["application"] == "some/app/text-to-image"
    assert fake.call["arguments"]["prompt"] == "a red cube"
    assert fake.call["arguments"]["resolution"] == "1K"
    assert fake.call["arguments"]["image_url"] == "https://ref/x.png"


def test_missing_credentials_raises(monkeypatch):
    from glitch_signal.media.generation.engines.base import EngineError
    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    monkeypatch.delenv("HIGGSFIELD_API_SECRET", raising=False)
    with pytest.raises(EngineError, match="HIGGSFIELD"):
        HiggsfieldEngine()._credential()


def test_registry_resolves_higgsfield():
    from glitch_signal.media.generation.engines import get_engine
    assert get_engine("higgsfield").name == "higgsfield"


def test_soul_recipe_loads_with_vendor_skill():
    from glitch_signal.media.generation import get_recipe
    r = get_recipe("higgsfield-soul-image")
    assert r.engine == "higgsfield"
    assert r.phases[0].model == "higgsfield-ai/soul/v2/standard"   # a real account slug
    assert "higgsfield" in r.skill_md.lower() and len(r.skill_md) > 10_000  # bundled vendor SKILL.md


async def test_soul_recipe_routes_to_higgsfield():
    from glitch_signal.media.generation import generate
    from glitch_signal.media.generation.spec import Brief

    class _FakeEng:
        name = "higgsfield"

        def __init__(self):
            self.call = None

        async def generate(self, model, prompt, *, images=None, params=None, timeout_s=360):
            self.call = {"model": model, "prompt": prompt, "params": params}
            return "https://cdn/soul.png"

    eng = _FakeEng()
    asset = await generate(Brief(brand_id="glitch_executor", recipe="higgsfield-soul-image",
                                 inputs={"prompt": "a red cube"}), engine=eng)
    assert eng.call["model"] == "higgsfield-ai/soul/v2/standard"
    assert eng.call["prompt"] == "a red cube"
    assert asset.url == "https://cdn/soul.png"
