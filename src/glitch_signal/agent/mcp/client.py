"""MCP client — connect to external tools' MCP servers, discover tools, call them.

Per brand, `MCP_SERVERS` (resolved via `brand_env`) is a JSON array of server specs:

    [{"name": "heygen", "url": "https://mcp.heygen.com/mcp",
      "headers": {"X-Api-Key": "sk_..."}}]

`MCPManager` opens every configured server (streamable-HTTP), lists their tools, and namespaces
them `mcp__<server>__<tool>` so they can't collide with the loop's built-in tools. The network
transport is isolated behind an injectable `connector`, so this unit-tests without a server.
Results are **untrusted** — they come back as observations the loop reads, never as instructions.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)

_DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


@dataclass(frozen=True)
class ServerSpec:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


def parse_servers(raw: str | None) -> list[ServerSpec]:
    """Parse a brand's MCP_SERVERS JSON into specs (bad/empty config → no servers)."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.mcp.bad_config", error=str(exc)[:160])
        return []
    out: list[ServerSpec] = []
    for item in data if isinstance(data, list) else []:
        name, url = (item.get("name") or "").strip(), (item.get("url") or "").strip()
        if name and url:
            out.append(ServerSpec(name=name, url=url, headers=dict(item.get("headers") or {})))
    return out


# A session exposes the two calls we use; the real one comes from the mcp SDK.
class _Session:  # pragma: no cover - structural type only
    async def initialize(self) -> Any: ...
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict) -> Any: ...


Connector = Callable[[ServerSpec, AsyncExitStack], Awaitable[_Session]]


async def _default_connector(spec: ServerSpec, stack: AsyncExitStack) -> _Session:
    """Open a streamable-HTTP MCP session (real network). Imported lazily so import never fails."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    # A browser-like UA is required — some MCP hosts sit behind Cloudflare, which blocks
    # default SDK/urllib agents (HeyGen returns CF error 1010 otherwise).
    headers = {"User-Agent": _DEFAULT_UA, **(spec.headers or {})}
    http_client = create_mcp_http_client(headers=headers)
    streams = await stack.enter_async_context(
        streamable_http_client(spec.url, http_client=http_client)
    )
    read, write = streams[0], streams[1]  # TransportStreams: (read, write[, get_session_id])
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


def _result_text(result: Any) -> str:
    """Extract text from a CallToolResult's content blocks."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


class MCPManager:
    """Opens the brand's MCP servers, discovers tools, and routes namespaced calls."""

    def __init__(self, servers: list[ServerSpec], *, connector: Connector | None = None) -> None:
        self._servers = servers
        self._connector = connector or _default_connector
        self._stack = AsyncExitStack()
        self._sessions: dict[str, _Session] = {}
        self._tools: dict[str, tuple[str, str, str]] = {}  # ns -> (server, tool, description)

    async def __aenter__(self) -> "MCPManager":
        for spec in self._servers:
            try:
                session = await self._connector(spec, self._stack)
                self._sessions[spec.name] = session
                resp = await session.list_tools()
                for tool in getattr(resp, "tools", None) or []:
                    ns = f"mcp__{spec.name}__{tool.name}"
                    self._tools[ns] = (spec.name, tool.name, getattr(tool, "description", "") or "")
                log.info("agent.mcp.connected", server=spec.name, tools=len(self._tools))
            except Exception as exc:  # noqa: BLE001 — one bad server must not kill the run
                log.warning("agent.mcp.connect_failed", server=spec.name, error=str(exc)[:200])
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    def tool_descriptions(self) -> dict[str, str]:
        return {ns: desc for ns, (_s, _t, desc) in self._tools.items()}

    def has(self, namespaced: str) -> bool:
        return namespaced in self._tools

    async def call(self, namespaced: str, args: dict) -> str:
        spec = self._tools.get(namespaced)
        if spec is None:
            return f"ERROR: unknown MCP tool {namespaced!r}"
        server, tool, _desc = spec
        try:
            result = await self._sessions[server].call_tool(tool, args or {})
        except Exception as exc:  # noqa: BLE001 — surface to the loop, don't crash it
            return f"ERROR: MCP {namespaced} failed: {str(exc)[:200]}"
        if getattr(result, "isError", False):
            return f"ERROR: MCP {namespaced}: {_result_text(result)[:300]}"
        return _result_text(result) or "(no content)"


async def manager_for_brand(brand_id: str, *, connector: Connector | None = None) -> MCPManager:
    """Build an (unentered) MCPManager from the agent-wide + per-brand MCP servers.

    `AGENT_MCP_SERVERS` (global infra, e.g. the MeshPilot HeyGen account) applies to every brand;
    `<BRAND>_MCP_SERVERS` adds project-specific servers. Same-name brand servers override global.
    """
    import os

    from glitch_signal.config import brand_env

    servers = parse_servers(os.environ.get("AGENT_MCP_SERVERS"))
    by_name = {s.name: s for s in servers}
    for s in parse_servers(brand_env("MCP_SERVERS", brand_id)):
        by_name[s.name] = s
    return MCPManager(list(by_name.values()), connector=connector)
