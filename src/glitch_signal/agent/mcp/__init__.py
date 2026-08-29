"""AGENT-MCP — the brain loop as an MCP client: connect to external tools' MCP servers,
discover their tools, and call them (policy-gated)."""
from glitch_signal.agent.mcp.client import (
    MCPManager,
    ServerSpec,
    manager_for_brand,
    parse_servers,
)

__all__ = ["MCPManager", "ServerSpec", "manager_for_brand", "parse_servers"]
