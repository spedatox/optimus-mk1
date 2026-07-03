"""tools/task_stop_tool/task_stop_tool.py — port of
src/tools/TaskStopTool/TaskStopTool.ts (verified against source).

Porting notes:
  - appState.tasks registry → optimus.tasks.task_registry (same role: id →
    task handle with status/type/description).
  - stopTask() framework helper → handle.stop(); command falls back to the
    handle description.
  - renderToolUseMessage / renderToolResultMessage (UI.tsx) → None.
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
from optimus.tasks.task_registry import get_task_registry
from optimus.tools.task_stop_tool.prompt import DESCRIPTION, TASK_STOP_TOOL_NAME

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "The ID of the background task to stop"},
        "shell_id": {"type": "string", "description": "Deprecated: use task_id instead"},
    },
    "required": [],
    "additionalProperties": False,
}


@build_tool
class TaskStopTool:
    name = TASK_STOP_TOOL_NAME
    # KillShell is the deprecated name — kept as alias for backward
    # compatibility with existing transcripts and SDK users.
    aliases = ["KillShell"]
    search_hint = "kill a running background task"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return "Stop a running background task by ID"

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        # Source: '' for ant builds, 'Stop Task' externally.
        return "Stop Task"

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("task_id") or input.get("shell_id") or ""

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        task_id = input.get("task_id") or input.get("shell_id")
        if not task_id:
            return ValidationResult.fail("Missing required parameter: task_id", error_code=1)
        task = get_task_registry().get(task_id)
        if task is None:
            return ValidationResult.fail(f"No task found with ID: {task_id}", error_code=1)
        if task.status != "running":
            return ValidationResult.fail(
                f"Task {task_id} is not running (status: {task.status})", error_code=3
            )
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
        task_id = input.get("task_id") or input.get("shell_id")
        if not task_id:
            raise ValueError("Missing required parameter: task_id")
        task = get_task_registry().get(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")

        await task.stop()
        command = getattr(task, "command", None) or task.description
        return ToolResult(data={
            "message": f"Successfully stopped task: {task_id} ({command})",
            "task_id": task_id,
            "task_type": task.task_type,
            "command": command,
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": json.dumps(data)}
