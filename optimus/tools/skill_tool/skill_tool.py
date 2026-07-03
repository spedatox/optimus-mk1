"""tools/skill_tool/skill_tool.py — port of src/tools/SkillTool (restored from
commit f696afe, upgraded to the current Tool protocol).

Executes a registered skill (slash command): looks the command up in the
commands registry (markdown files under .claude/commands/ and ~/.claude/
commands/), expands $ARGUMENTS, and returns the expanded prompt as the tool
result so the model executes the skill's instructions in the current turn.
"""
from __future__ import annotations

from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.commands import expand_command, find_command, get_commands
from optimus.tools.skill_tool.prompt import DESCRIPTION, PROMPT, SKILL_TOOL_NAME

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill": {
            "type": "string",
            "description": 'The skill name (e.g. "commit", "frontend:deploy"). No leading slash.',
        },
        "args": {
            "type": "string",
            "description": "Optional arguments for the skill.",
        },
    },
    "required": ["skill"],
    "additionalProperties": False,
}


@build_tool
class SkillTool:
    name = SKILL_TOOL_NAME
    search_hint = "run a slash command / custom skill"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        # Expanding a prompt template does not touch the filesystem; the
        # instructions it yields go through normal tool permissions afterwards.
        return True

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        if input and input.get("skill"):
            return f"/{input['skill'].lstrip('/')}"
        return SKILL_TOOL_NAME

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("skill", "")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("skill", "").strip():
            return ValidationResult.fail("skill must not be empty", error_code=1)
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
        skill_name = input["skill"].lstrip("/")
        args = input.get("args") or ""

        commands = get_commands()
        command = find_command(skill_name, commands)
        if command is None:
            available = ", ".join(sorted(c.name for c in commands)) or "(none found)"
            return ToolResult(data={
                "found": False,
                "skill": skill_name,
                "error": f"Skill '{skill_name}' not found. Available skills: {available}",
            })

        return ToolResult(data={
            "found": True,
            "skill": skill_name,
            "prompt": expand_command(command, args),
            "args": args,
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if not data.get("found"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        content = (
            f"Skill '{data['skill']}' loaded. Follow these instructions now:\n\n"
            f"{data['prompt']}"
        )
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
