"""tools/read_mcp_resource_tool/read_mcp_resource_tool.py — port of
src/tools/ReadMcpResourceTool (restored from commit f696afe, upgraded to the
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
from optimus.tools.read_mcp_resource_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    READ_MCP_RESOURCE_TOOL_NAME,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "server": {"type": "string", "description": "The MCP server name"},
        "uri": {"type": "string", "description": "The resource URI to read"},
    },
    "required": ["server", "uri"],
    "additionalProperties": False,
}


@build_tool
class ReadMcpResourceTool:
    name = READ_MCP_RESOURCE_TOOL_NAME
    search_hint = "read an MCP server resource by uri"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 200_000
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

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("server", "").strip():
            return ValidationResult.fail("server must not be empty", error_code=1)
        if not input.get("uri", "").strip():
            return ValidationResult.fail("uri must not be empty", error_code=2)
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
        try:
            contents = await get_mcp_manager().read_resource(
                server=input["server"], uri=input["uri"]
            )
        except Exception as exc:
            return ToolResult(data={"error": f"Error reading resource: {exc}"})
        return ToolResult(data={"contents": contents})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result", "content": json.dumps(data["contents"]),
                "tool_use_id": tool_use_id}
