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
