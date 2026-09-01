"""edit_image SSRF guard (#192) — the fetch must connect to the SAME address the guard validated.

Before the fix, `edit_image` called `assert_safe_media_url(url)` (which resolves DNS itself) and
then fetched the *original hostname URL* through a fresh httpx client — httpx re-resolves DNS at
request time, so a DNS-rebinding host could answer the guard's lookup with a public IP and the
fetch's lookup with a private/metadata IP (classic TOCTOU). The fix resolves the host ONCE via
`tools._web_url_resolve` (async, non-blocking) and pins the actual httpx connection to that exact
validated IP via `tools._pin_url`, mirroring the pattern already used by `web_fetch`.
"""
from __future__ import annotations

import asyncio

import glitch_signal.agent.loop.tools as tools


class _Resp:
    def __init__(self, status=200, content=b"fake-image-bytes"):
        self.status_code = status
        self.content = content


class _CaptureClient:
    """Fake httpx.AsyncClient that records the exact url/headers/extensions used to GET."""
    last_call: dict = {}

    def __init__(self, *a, **k):
        self.init_kwargs = k

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **k):
        _CaptureClient.last_call = {"url": url, **k}
        return _Resp()


def _patch_edit_deps(monkeypatch):
    """Stub out the parts of edit_image that aren't the SSRF path under test."""
    monkeypatch.setattr("glitch_signal.media.imaging.apply_ops", lambda data, ops: data)

    async def _upload(data, brand_id, *, ext, content_type, prefix):
        return f"https://cdn.example/{prefix}.{ext}"

    monkeypatch.setattr("glitch_signal.media.generation.storage.upload_bytes", _upload)


async def test_edit_image_pins_connection_to_resolved_ip_not_hostname(monkeypatch):
    """The regression test for #192: prove the actual httpx GET targets the validated IP, not the
    original hostname — i.e. there is no second, unvalidated DNS resolution at fetch time."""
    _patch_edit_deps(monkeypatch)

    async def _fake_getaddrinfo(host, port, **k):
        return [(2, 1, 6, "", ("93.184.216.34", port))]  # a public address the guard approves

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_getaddrinfo)
    monkeypatch.setattr("httpx.AsyncClient", _CaptureClient)

    out = await tools._t_edit_image({"image_url": "https://rebind.example/img.png", "ops": []}, "brand")

    assert out.startswith("edited image")
    call = _CaptureClient.last_call
    # The connection must go to the pinned IP — the hostname must NOT appear in the request URL.
    assert "93.184.216.34" in call["url"]
    assert "rebind.example" not in call["url"]
    # Host header + SNI stay bound to the real hostname so TLS verification is unaffected.
    assert call["headers"]["host"] == "rebind.example"
    assert call["extensions"]["sni_hostname"] == "rebind.example"


async def test_edit_image_rejects_dns_rebinding_to_private_address(monkeypatch):
    """If the (single) resolution turns up a non-public address, refuse before ever calling httpx —
    this is what stops the metadata/RFC-1918 pivot described in #192."""
    _patch_edit_deps(monkeypatch)

    async def _fake_getaddrinfo(host, port, **k):
        return [(2, 1, 6, "", ("169.254.169.254", port))]  # cloud metadata address

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_getaddrinfo)

    def _boom(*a, **k):
        raise AssertionError("httpx.AsyncClient must not be constructed when the guard refuses")

    monkeypatch.setattr("httpx.AsyncClient", _boom)

    out = await tools._t_edit_image({"image_url": "https://rebind.example/img.png", "ops": []}, "brand")
    assert out.startswith("ERROR: unsafe image_url") and "non-public" in out


async def test_edit_image_rejects_non_https():
    assert (await tools._t_edit_image({"image_url": "http://example.com/x.png"}, "brand")) \
        .startswith("ERROR: unsafe image_url: only https")


async def test_edit_image_requires_url():
    assert (await tools._t_edit_image({}, "brand")).startswith("ERROR: edit_image requires image_url")


# ── #196: _pin_url must bracket IPv6 literals in both the pinned URL authority and the Host
#    header, or the port becomes ambiguous with the address's own colons (an invalid authority /
#    malformed Host header) — RFC 3986 / RFC 7230 both require `[addr]:port` for an IPv6 literal.

def test_pin_url_brackets_ipv6_resolved_ip():
    # host is an ordinary hostname; the resolved `ip` is IPv6 — the pinned URL's netloc must bracket it.
    pinned, host_header = tools._pin_url("https://example.com:443/path?q=1", "example.com", "2001:db8::1")
    assert pinned == "https://[2001:db8::1]:443/path?q=1"
    assert host_header == "example.com:443"


def test_pin_url_brackets_ipv6_host_in_host_header():
    # the ORIGINAL url used an IPv6 literal host (urlsplit().hostname strips the brackets), and it
    # resolved to itself — the Host header must re-bracket it, not emit "::1:8080".
    pinned, host_header = tools._pin_url("https://[::1]:8080/x", "::1", "::1")
    assert pinned == "https://[::1]:8080/x"
    assert host_header == "[::1]:8080"


def test_pin_url_ipv6_no_port():
    pinned, host_header = tools._pin_url("https://example.com/x", "example.com", "fe80::1")
    assert pinned == "https://[fe80::1]/x"
    assert host_header == "example.com"


def test_pin_url_ipv4_unbracketed():
    pinned, host_header = tools._pin_url("https://example.com:8443/x", "example.com", "93.184.216.34")
    assert pinned == "https://93.184.216.34:8443/x"
    assert host_header == "example.com:8443"
