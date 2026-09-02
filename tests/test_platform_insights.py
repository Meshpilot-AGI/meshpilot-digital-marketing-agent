"""Meta insights reads — an empty Graph dataset must never become a recorded measurement.

Meta documents that unavailable insight data comes back as an EMPTY dataset, not zeros. Before this
fix, `facebook_post`/`instagram_media` always returned a dict — even when every field flattened to
None — so `outcomes.collect` would persist an all-NULL row and permanently mark that age bucket
"measured" for a post that was never actually read. See platforms/insights.py's `_measured` and the
module docstring's "unmeasurable records nothing" invariant.
"""
from glitch_signal.platforms import insights


class _Resp:
    def __init__(self, json_data=None, status=200):
        self._json = json_data or {}
        self.status_code = status

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _FakeClient:
    """Routes each GET by the last path segment — enough to tell the token/insights/engagement
    calls apart without needing a real Graph endpoint."""

    def __init__(self, by_suffix: dict[str, dict]):
        self.by_suffix = by_suffix

    headers_seen: list = []

    async def get(self, url, params=None, headers=None):
        # `headers` is required: the token moved out of the query string into an Authorization
        # header, because httpx echoes the request URL in its exception text and these calls log
        # on failure by design (PR #205 token-leak finding).
        self.headers_seen.append(headers or {})
        for suffix, payload in self.by_suffix.items():
            if url.endswith(suffix):
                return _Resp(payload)
        raise AssertionError(f"unexpected url in test: {url}")


def _patch_fb_creds(monkeypatch, page_id="pg1", token="sys-token"):
    monkeypatch.setattr("glitch_signal.platforms.insights.resolve_facebook_creds",
                        lambda brand_id=None: (page_id, token))


async def test_facebook_post_with_no_usable_metric_returns_none(monkeypatch):
    """An empty Graph insights dataset (no rows) plus an engagement read with nothing set must
    flatten to an all-None dict — and that must come back as None, not a measurement of zero."""
    _patch_fb_creds(monkeypatch)
    client = _FakeClient({
        "/pg1": {"access_token": "page-token"},
        "post1/insights": {"data": []},                    # empty dataset — Meta's "unavailable"
        "post1": {},                                        # no comments/shares/reactions at all
    })
    result = await insights.facebook_post("post1", client=client)
    assert result is None


async def test_facebook_post_with_a_real_metric_is_recorded(monkeypatch):
    _patch_fb_creds(monkeypatch)
    client = _FakeClient({
        "/pg1": {"access_token": "page-token"},
        "post1/insights": {"data": [{"name": "post_clicks", "values": [{"value": 3}]}]},
        "post1": {},
    })
    result = await insights.facebook_post("post1", client=client)
    assert result is not None
    assert result["clicks"] == 3


async def test_instagram_media_with_empty_dataset_returns_none(monkeypatch):
    _patch_fb_creds(monkeypatch)
    client = _FakeClient({"media1/insights": {"data": []}})
    result = await insights.instagram_media("media1", client=client)
    assert result is None


async def test_instagram_media_with_a_real_metric_is_recorded(monkeypatch):
    _patch_fb_creds(monkeypatch)
    client = _FakeClient({
        "media1/insights": {"data": [{"name": "likes", "values": [{"value": 12}]}]},
    })
    result = await insights.instagram_media("media1", client=client)
    assert result is not None
    assert result["likes"] == 12


def test_no_call_puts_the_token_in_a_query_string():
    """Regression for the #205 leak: the fake now records headers, so this asserts the credential
    travels in the Authorization header and never in params (httpx echoes the URL in its exception
    text, and these calls log on failure by design)."""
    import asyncio

    from glitch_signal.platforms import insights

    seen_params: list = []

    class _Spy:
        async def get(self, url, params=None, headers=None):
            seen_params.append(params or {})
            assert headers and headers.get("Authorization", "").startswith("Bearer ")
            return _Resp({"data": [], "access_token": "page-tok"})

    asyncio.run(insights.facebook_post("p1", brand_id="glitch_executor", client=_Spy()))
    assert all("access_token" not in p for p in seen_params)
