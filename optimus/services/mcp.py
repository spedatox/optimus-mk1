"""
services/mcp.py — MCP server manager.

Restored from the pre-restructure port (commit f696afe). Manages connected MCP
server clients and proxies resource listing/reading, tool calls, and OAuth
flows. Clients are registered by the bootstrap path once the `mcp` SDK
connections are established (RE-ENTRY: full services/mcp/ client stack —
transport negotiation, .mcp.json discovery, scope dialogs — not yet ported;
this manager is the stable surface the MCP tools talk to).
"""
from __future__ import annotations

from typing import Any, Optional

_manager: Optional["MCPManager"] = None


class MCPManager:
    """Manages connections to MCP servers and proxies tool/resource calls."""

    def __init__(self) -> None:
        self._servers: dict[str, Any] = {}

    async def list_resources(self, server_filter: str | None = None) -> list[dict]:
        results = []
        for server_name, client in self._servers.items():
            if server_filter and server_name != server_filter:
                continue
            try:
                resources = await client.list_resources()
                for r in resources:
                    results.append({
                        "uri": str(r.uri),
                        "name": r.name,
                        "mimeType": getattr(r, "mimeType", None),
                        "description": getattr(r, "description", None),
                        "server": server_name,
                    })
            except Exception:
                # A dead server should not break listing across the rest.
                pass
        return results

    async def read_resource(self, server: str, uri: str) -> list[dict]:
        client = self._require(server)
        result = await client.read_resource(uri)
        contents = []
        for item in result.contents:
            contents.append({
                "uri": str(item.uri),
                "mimeType": getattr(item, "mimeType", None),
                "text": getattr(item, "text", None),
            })
        return contents

    async def call_tool(self, server: str, tool_name: str, arguments: dict) -> Any:
        client = self._require(server)
        return await client.call_tool(tool_name, arguments)

    async def start_auth(self, server: str) -> str:
        client = self._require(server)
        return await client.start_auth()

    async def complete_auth(self, server: str, code: str) -> None:
        client = self._require(server)
        await client.complete_auth(code)

    async def get_auth_status(self, server: str) -> str:
        client = self._servers.get(server)
        if client is None:
            return "not_connected"
        return await client.get_auth_status()

    def register_server(self, name: str, client: Any) -> None:
        self._servers[name] = client

    def unregister_server(self, name: str) -> None:
        self._servers.pop(name, None)

    def get_server_names(self) -> list[str]:
        return list(self._servers.keys())

    def _require(self, server: str) -> Any:
        client = self._servers.get(server)
        if client is None:
            known = ", ".join(self.get_server_names()) or "none"
            raise ValueError(f"MCP server '{server}' not connected. Connected servers: {known}")
        return client


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
