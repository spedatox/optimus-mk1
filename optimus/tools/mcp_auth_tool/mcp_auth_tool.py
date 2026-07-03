"""tools/mcp_auth_tool/mcp_auth_tool.py — port of src/tools/McpAuthTool
(restored from commit f696afe, upgraded to the current Tool protocol)."""
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
from optimus.tools.mcp_auth_tool.prompt import DESCRIPTION, MCP_AUTH_TOOL_NAME, PROMPT

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "server": {"type": "string", "description": "MCP server name to authenticate"},
        "action": {
            "type": "string",
            "enum": ["start", "complete", "status"],
            "description": "Authentication action",
        },
        "code": {"type": "string", "description": "OAuth authorization code (for 'complete')"},
    },
    "required": ["server", "action"],
    "additionalProperties": False,
}


@build_tool
class McpAuthTool:
    name = MCP_AUTH_TOOL_NAME
    search_hint = "authenticate an MCP server via oauth"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 20_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return (input or {}).get("action") == "status"

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if input.get("action") == "complete" and not input.get("code"):
            return ValidationResult.fail("code is required for the 'complete' action", error_code=1)
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        server: str = input["server"]
        action: str = input["action"]
        manager = get_mcp_manager()
        try:
            if action == "start":
                auth_url = await manager.start_auth(server)
                result = {"status": "pending", "auth_url": auth_url, "server": server}
            elif action == "complete":
                await manager.complete_auth(server, input["code"])
                result = {"status": "authenticated", "server": server}
            else:  # status
                status = await manager.get_auth_status(server)
                result = {"status": status, "server": server}
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "server": server}
        return ToolResult(data=result)

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "content": json.dumps(data),
            "tool_use_id": tool_use_id,
        }
        if data.get("status") == "error":
            block["is_error"] = True
        return block
