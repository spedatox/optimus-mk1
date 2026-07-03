"""tools/team_delete_tool/team_delete_tool.py — port of src/tools/TeamDeleteTool
(restored from commit f696afe, upgraded to the current Tool protocol)."""
from __future__ import annotations

from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.team_delete_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    TEAM_DELETE_TOOL_NAME,
)
from optimus.utils.swarm.team_helpers import (
    cleanup_team_directories,
    get_current_team_name,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@build_tool
class TeamDeleteTool:
    name = TEAM_DELETE_TOOL_NAME
    search_hint = "disband the current swarm team"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 10_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return False  # deletes the team file

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
        team_name = get_current_team_name()
        if not team_name:
            return ToolResult(data={"success": False, "message": "No active team found."})
        try:
            await cleanup_team_directories(team_name)
        except Exception as exc:
            return ToolResult(data={
                "success": False,
                "message": f"Error cleaning up team '{team_name}': {exc}",
            })
        return ToolResult(data={
            "success": True,
            "team_name": team_name,
            "message": f"Team '{team_name}' disbanded and resources cleaned up.",
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "tool_result", "content": data["message"],
                                 "tool_use_id": tool_use_id}
        if not data.get("success"):
            block["is_error"] = True
        return block
