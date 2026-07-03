"""tools/team_create_tool/team_create_tool.py — port of src/tools/TeamCreateTool
(restored from commit f696afe, upgraded to the current Tool protocol)."""
from __future__ import annotations

import json
import secrets
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.team_create_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    TEAM_CREATE_TOOL_NAME,
)
from optimus.utils.swarm.team_helpers import (
    get_team_file_path,
    sanitize_name,
    write_team_file,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "team_name": {"type": "string", "description": "Name for the new team to create"},
        "description": {"type": "string", "description": "Team description/purpose"},
        "agent_type": {
            "type": "string",
            "description": "Type/role of the team lead (e.g. 'researcher', 'test-runner')",
        },
    },
    "required": ["team_name"],
    "additionalProperties": False,
}


@build_tool
class TeamCreateTool:
    name = TEAM_CREATE_TOOL_NAME
    search_hint = "create a multi-agent swarm team"
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
        return False  # writes the team file

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("team_name", "").strip():
            return ValidationResult.fail("team_name must not be empty", error_code=1)
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
        team_name = sanitize_name(input["team_name"])
        agent_type = input.get("agent_type") or "general"
        lead_agent_id = f"agent-{secrets.token_hex(6)}"

        team_data = {
            "team_name": team_name,
            "description": input.get("description") or "",
            "agent_type": agent_type,
            "lead_agent_id": lead_agent_id,
            "agents": [{"id": lead_agent_id, "role": "lead", "type": agent_type}],
        }
        try:
            await write_team_file(team_name, team_data)
        except Exception as exc:
            return ToolResult(data={"error": f"Error creating team: {exc}"})

        return ToolResult(data={
            "team_name": team_name,
            "team_file_path": get_team_file_path(team_name),
            "lead_agent_id": lead_agent_id,
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result", "content": json.dumps(data), "tool_use_id": tool_use_id}
