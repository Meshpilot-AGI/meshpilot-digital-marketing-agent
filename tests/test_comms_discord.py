"""The Discord alert channel — a webhook, no bot, no gateway."""
from __future__ import annotations

import httpx

from glitch_signal.comms import discord

HOOK = "https://discord.com/api/webhooks/1/abc"


class _Client:
    def __init__(self, status=204, boom=False):
        self.status, self.boom, self.posts = status, boom, []

    async def post(self, url, json=None):
        if self.boom:
            raise httpx.ConnectError("no route")
        self.posts.append((url, json))
        return httpx.Response(self.status, text="" if self.status < 400 else "bad webhook")

    async def aclose(self):
        pass


async def test_a_successful_post():
    c = _Client()
    assert await discord.post_alert("hello", webhook_url=HOOK, client=c) is True
    assert c.posts[0][1]["content"] == "hello"


async def test_a_long_message_is_truncated_rather_than_rejected():
    """Discord refuses a body over 2000 characters outright — an alert that is too long to send is
    an alert that does not arrive."""
    c = _Client()
    await discord.post_alert("x" * 5000, webhook_url=HOOK, client=c)
    assert len(c.posts[0][1]["content"]) <= 1900


async def test_a_rejected_webhook_returns_false_rather_than_raising():
    """An alerting path that throws takes down the monitor calling it — the one component that must
    survive whatever it is reporting on."""
    assert await discord.post_alert("hi", webhook_url=HOOK, client=_Client(status=401)) is False


async def test_a_network_error_returns_false_rather_than_raising():
    assert await discord.post_alert("hi", webhook_url=HOOK, client=_Client(boom=True)) is False


async def test_an_empty_url_is_a_no_op():
    assert await discord.post_alert("hi", webhook_url="") is False


def test_only_a_real_webhook_url_counts_as_configured():
    """A placeholder left in the env should read as "not configured", not as a broken channel."""
    assert discord.is_configured(HOOK)
    assert not discord.is_configured("set-me-later")
    assert not discord.is_configured("https://example.com/hook")
    assert not discord.is_configured(None)


# ── provisioning the alerts channel (SEO-11) ──
class _Api:
    """Stands in for the Discord REST API."""

    def __init__(self, guilds=None, channels=None, webhooks=None):
        self.guilds = guilds if guilds is not None else [{"id": "9", "name": "MeshPilot"}]
        self.channels = channels if channels is not None else []
        self.webhooks = webhooks if webhooks is not None else []
        self.calls = []

    async def __call__(self, method, path, token, *, json_body=None):
        self.calls.append((method, path))
        if path == "/users/@me/guilds":
            return self.guilds
        if path.endswith("/channels") and method == "GET":
            return self.channels
        if path.endswith("/channels") and method == "POST":
            made = {"id": "100", "name": json_body["name"], "type": 0}
            self.channels.append(made)
            return made
        if path.endswith("/webhooks") and method == "GET":
            return self.webhooks
        if path.endswith("/webhooks") and method == "POST":
            hook = {"id": "5", "name": json_body["name"], "token": "t0k",
                    "url": "https://discord.com/api/webhooks/5/t0k"}
            self.webhooks.append(hook)
            return hook
        raise AssertionError(f"unexpected {method} {path}")


async def test_it_creates_the_channel_and_the_webhook(monkeypatch):
    api = _Api()
    monkeypatch.setattr(discord, "_api", api)
    res = await discord.provision_alert_channel(token="bot")
    assert res["created_channel"] and res["url"].startswith("https://discord.com/api/webhooks/")


async def test_re_running_reuses_both_rather_than_duplicating(monkeypatch):
    """Idempotent at both steps: a duplicate channel litters the server, and a second webhook would
    silently double every alert."""
    api = _Api(channels=[{"id": "100", "name": "alerts", "type": 0}],
               webhooks=[{"id": "5", "name": "MeshPilot", "token": "t0k",
                          "url": "https://discord.com/api/webhooks/5/t0k"}])
    monkeypatch.setattr(discord, "_api", api)
    res = await discord.provision_alert_channel(token="bot")
    assert res["created_channel"] is False
    assert not [c for c in api.calls if c[0] == "POST"]


async def test_a_voice_channel_of_the_same_name_is_not_mistaken_for_it(monkeypatch):
    """`type` 0 is a text channel. Posting a webhook to a voice channel of the same name would fail
    in a way nobody would connect back to this."""
    api = _Api(channels=[{"id": "77", "name": "alerts", "type": 2}])
    monkeypatch.setattr(discord, "_api", api)
    res = await discord.provision_alert_channel(token="bot")
    assert res["created_channel"] is True


async def test_several_guilds_demands_an_explicit_choice(monkeypatch):
    """Guessing which server to create a channel in is not ours to guess."""
    import pytest

    api = _Api(guilds=[{"id": "1", "name": "A"}, {"id": "2", "name": "B"}])
    monkeypatch.setattr(discord, "_api", api)
    with pytest.raises(RuntimeError, match="pass guild_id"):
        await discord.provision_alert_channel(token="bot")
