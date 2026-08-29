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
