"""tools/list_mcp_resources_tool/list_mcp_resources_tool.py — port of
src/tools/ListMcpResourcesTool (restored from commit f696afe, upgraded to the
current Tool protocol)."""
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
from optimus.tools.list_mcp_resources_tool.prompt import (
    DESCRIPTION,
    LIST_MCP_RESOURCES_TOOL_NAME,
    PROMPT,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "server": {"type": "string", "description": "Optional server name to filter resources by"},
    },
    "required": [],
    "additionalProperties": False,
}


@build_tool
class ListMcpResourcesTool:
    name = LIST_MCP_RESOURCES_TOOL_NAME
    search_hint = "list resources exposed by MCP servers"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

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
        resources = await get_mcp_manager().list_resources(server_filter=input.get("server"))
        return ToolResult(data={"resources": resources})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        resources = data.get("resources", [])
        content = json.dumps(resources) if resources else "No MCP resources available."
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
