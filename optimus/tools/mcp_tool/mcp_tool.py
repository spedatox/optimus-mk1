"""tools/mcp_tool/mcp_tool.py — dynamic MCP tool wrapper (restored from commit
f696afe, upgraded to the current Tool protocol).

The MCP manager builds one MCPTool instance per tool advertised by a connected
server (make_mcp_tool). Calls proxy through services/mcp.py; results are the
server's content blocks mapped into a tool_result block.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.services.mcp import get_mcp_manager

_DEFAULT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}


@build_tool
class MCPTool:
    """One instance per (server, tool) pair; fields set by make_mcp_tool()."""

    name = "mcp"
    is_mcp = True
    should_defer = True
    max_result_size_chars = 200_000
    input_schema = _DEFAULT_SCHEMA

    def __init__(
        self,
        server_name: str = "",
        tool_name: str = "",
        description: str = "",
        input_schema: Optional[dict[str, Any]] = None,
    ) -> None:
        if server_name and tool_name:
            self.name = f"mcp__{server_name}__{tool_name}"
        self._server_name = server_name
        self._mcp_tool_name = tool_name
        self._description = description or "MCP tool — details provided by connected server."
        if input_schema:
            self.input_schema = input_schema
        self.mcp_info = {"server": server_name, "tool": tool_name}

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return self._description

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return self._description

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return f"{self._server_name}:{self._mcp_tool_name}" if self._server_name else self.name

    def is_open_world(self, input: dict[str, Any]) -> bool:
        return True  # server behavior is outside our control

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        # MCP tools prompt by default; user allowlists per-tool via rules.
        return PermissionResult(
            behavior="ask", updated_input=input,
            message=f"Call MCP tool {self.user_facing_name(input)}?",
        )

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        try:
            result = await get_mcp_manager().call_tool(
                server=self._server_name,
                tool_name=self._mcp_tool_name,
                arguments=input,
            )
        except Exception as exc:
            return ToolResult(data={"error": f"MCP tool error: {exc}"})

        # Normalize the SDK result to plain content blocks.
        blocks: list[dict[str, Any]] = []
        content = getattr(result, "content", result)
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    blocks.append(item)
                elif getattr(item, "type", None) == "text":
                    blocks.append({"type": "text", "text": item.text})
                else:
                    blocks.append({"type": "text", "text": str(item)})
        elif isinstance(content, str):
            blocks.append({"type": "text", "text": content})
        else:
            blocks.append({"type": "text", "text": json.dumps(content, default=str)})
        return ToolResult(data={"content": blocks, "isError": bool(getattr(result, "isError", False))})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        text = "\n".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ) or "(no output)"
        block: dict[str, Any] = {"type": "tool_result", "content": text, "tool_use_id": tool_use_id}
        if data.get("isError"):
            block["is_error"] = True
        return block


def make_mcp_tool(
    server_name: str,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
) -> MCPTool:
    """Factory used by the MCP client to build a concrete tool wrapper."""
    return MCPTool(
        server_name=server_name,
        tool_name=tool_name,
        description=description,
        input_schema=input_schema,
    )
