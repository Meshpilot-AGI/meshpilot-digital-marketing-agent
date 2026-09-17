"""Gmail OAuth — read-only by construction, on the same rails as the YouTube flow."""
from __future__ import annotations

import httpx
import pytest

from glitch_signal.oauth import gmail as gmail_oauth


def test_the_scope_is_read_only():
    """A token that cannot send cannot send something embarrassing in the operator's name. The
    agent's reason to read mail is to find out what happened — no answer to that needs write."""
    assert gmail_oauth.SCOPES == "https://www.googleapis.com/auth/gmail.readonly"
    for forbidden in ("gmail.send", "gmail.modify", "gmail.compose", "mail.google.com"):
        assert forbidden not in gmail_oauth.SCOPES


def test_the_authorize_url_asks_for_offline_consent(monkeypatch):
    """The agent runs unattended, so it needs a refresh token: `access_type=offline` plus an explicit
    `prompt=consent`, which is what makes Google issue one on every grant."""
    monkeypatch.setattr(gmail_oauth, "_client_creds", lambda b: ("cid-123", "secret"))
    url = gmail_oauth.build_authorize_url("tejas")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "gmail.readonly" in url
    assert "include_granted_scopes" not in url, \
        "this grant should carry gmail.readonly alone — a token's powers must be legible from its row"


def test_client_creds_fall_back_to_the_shared_google_client(monkeypatch):
    """It is ONE GCP OAuth client with several scopes, so a brand that already connected YouTube
    should not have to duplicate the credentials to connect Gmail."""
    seen = {}

    def fake_env(name, brand_id):
        seen[name] = True
        return {"TKA_YOUTUBE_CLIENT_ID": "yt-id", "TKA_YOUTUBE_CLIENT_SECRET": "yt-sec"}.get(
            f"TKA_{name}")

    monkeypatch.setattr(gmail_oauth, "brand_env", lambda n, b: fake_env(n, b))
    assert gmail_oauth._client_creds("tejas") == ("yt-id", "yt-sec")
    assert "GMAIL_CLIENT_ID" in seen and "GOOGLE_CLIENT_ID" in seen, "tries the specific names first"


def test_an_unconfigured_client_names_what_is_missing(monkeypatch):
    monkeypatch.setattr(gmail_oauth, "brand_env", lambda n, b: None)
    with pytest.raises(RuntimeError, match="GMAIL_CLIENT_ID"):
        gmail_oauth._client_creds("tejas")


def test_a_state_token_from_another_platform_is_refused(monkeypatch):
    monkeypatch.setattr(gmail_oauth, "verify_state_token", lambda s: {"b": "tejas", "p": "youtube"})
    with pytest.raises(ValueError, match="platform mismatch"):
        gmail_oauth.parse_state("whatever")


async def test_search_is_silent_when_the_mailbox_is_not_connected(monkeypatch):
    """An unconnected mailbox is a configuration state the operator fixes by visiting
    /oauth/gmail/start — not an outage the caller should crash on."""
    from glitch_signal.integrations import gmail as gmail_api

    async def _no_token(_brand):
        raise RuntimeError("no auth row")

    monkeypatch.setattr(gmail_api, "_token", _no_token)
    assert await gmail_api.search("tejas", "from:greenhouse.io") == []


async def test_search_returns_message_headers(monkeypatch):
    from glitch_signal.integrations import gmail as gmail_api

    async def _tok(_brand):
        return "tok"

    monkeypatch.setattr(gmail_api, "_token", _tok)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        return httpx.Response(200, json={
            "snippet": "Thanks for applying to DEPT",
            "payload": {"headers": [{"name": "From", "value": "no-reply@greenhouse.io"},
                                    {"name": "Subject", "value": "Application received"}]}})

    got = await gmail_api.search("tejas", "from:greenhouse.io",
                                 client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert got[0]["subject"] == "Application received"
    assert got[0]["from"] == "no-reply@greenhouse.io"


def test_a_brand_without_credentials_gets_an_actionable_400_not_a_500(monkeypatch):
    """Observed live 2026-09-17: /oauth/gmail/start?brand=tejas returned 500 because the tejas brand
    had no Google client configured. A 500 says "something broke" and invites debugging the wrong
    layer; the true answer was "set two env vars", which belongs in a 400 that names them.

    Credentials stay strictly per brand — `brand_env` has no global fallback on purpose (never a
    global credential), so the fix is to declare TKA_GMAIL_CLIENT_ID/_SECRET, not to widen lookup."""
    from fastapi.testclient import TestClient

    from glitch_signal import server

    monkeypatch.setattr(server, "brand_ids", lambda: {"tejas"})
    monkeypatch.setattr(gmail_oauth, "brand_env", lambda n, b: None)
    r = TestClient(server.app, raise_server_exceptions=False).get("/oauth/gmail/start?brand=tejas")
    assert r.status_code == 400
    assert "GMAIL_CLIENT_ID" in r.json()["detail"]
