"""Network-safety helper — block SSRF on URLs that can be influenced by LLM/tool input.

The agent's `edit_image` tool fetches a URL chosen by the model (reachable via indirect prompt
injection through recalled memory or ingested briefs). Without a guard that is a full SSRF: cloud
metadata (169.254.169.254), RFC-1918 pivots, blind internal fetches. `assert_safe_media_url` requires
https and rejects any host that resolves to a non-public address. Pair it with `follow_redirects=False`
so a 3xx to an internal address can't bypass the check.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata"}


def assert_safe_media_url(url: str) -> None:
    """Raise ValueError unless `url` is https and every resolved IP is public."""
    p = urlparse(url)
    if p.scheme != "https":
        raise ValueError("only https URLs are allowed")
    host = (p.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS:
        raise ValueError(f"blocked host {host!r}")
    try:
        infos = socket.getaddrinfo(host, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve host {host!r}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"blocked non-public address {ip} for host {host!r}")
