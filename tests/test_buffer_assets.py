"""Buffer's CreatePostInput.assets shape — confirmed by introspecting the live schema.

Every image post to X, LinkedIn and TikTok failed with `Variable "$input" got invalid value
{ photos: [{ url: ... }] }`. The payload was a DICT; the schema declares:

    assets: [AssetInput!]!            -- a REQUIRED, NON-NULL LIST
    AssetInput { image | video | document }
    ImageAssetInput { url! , thumbnailUrl, metadata }

Two errors in one line: the wrong container (dict vs list) and the wrong keys (photos/videos vs
image/video). Guessing was never going to land it, which is why this stayed broken until the API key
was available to introspect with.
"""
import pytest

from glitch_signal.platforms import buffer


async def _captured(monkeypatch, media_url):
    seen = {}

    async def _graphql(token, query, variables=None, **k):
        seen["input"] = (variables or {})["input"]
        return {"createPost": {"__typename": "PostActionSuccess",
                               "post": {"id": "p1", "status": "sending"}}}

    async def _channel(brand_id, service):
        return "chan-1"

    monkeypatch.setattr(buffer, "_graphql", _graphql)
    monkeypatch.setattr(buffer, "_channel_id_for_service", _channel)
    monkeypatch.setattr(buffer, "_buffer_token", lambda b: "tok")
    await buffer.create_post("ge", "x", text="hello", media_url=media_url)
    return seen["input"]


async def test_assets_is_a_list_not_a_dict(monkeypatch):
    """The original bug: a dict where the schema declares [AssetInput!]!."""
    inp = await _captured(monkeypatch, "https://cdn/x.png")
    assert isinstance(inp["assets"], list)


async def test_an_image_uses_the_image_key_with_a_nested_url(monkeypatch):
    inp = await _captured(monkeypatch, "https://cdn/card.png")
    assert inp["assets"] == [{"image": {"url": "https://cdn/card.png"}}]


async def test_a_video_uses_the_video_key(monkeypatch):
    inp = await _captured(monkeypatch, "https://cdn/clip.mp4")
    assert inp["assets"] == [{"video": {"url": "https://cdn/clip.mp4"}}]


async def test_media_kind_is_decided_by_the_path_not_the_query_string(monkeypatch):
    """A signed URL's query string would defeat a naive endswith() and mis-file a video as an image."""
    inp = await _captured(monkeypatch, "https://cdn/clip.mp4?sig=abc&expires=1")
    assert "video" in inp["assets"][0]


async def test_a_text_only_post_sends_an_empty_list_not_a_missing_field(monkeypatch):
    """`assets` is NON_NULL, so omitting it is itself invalid — text-only posts must send []."""
    inp = await _captured(monkeypatch, None)
    assert inp["assets"] == []


async def test_the_old_dict_shape_is_gone():
    """Regression guard on the literal shape that broke production."""
    src = __import__("pathlib").Path(buffer.__file__).read_text()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert '"photos"' not in code and '"videos"' not in code
