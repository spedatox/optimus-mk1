"""tools/task_get_tool/task_get_tool.py — port of
src/tools/TaskGetTool/TaskGetTool.ts (verified against source)."""
from __future__ import annotations

from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.task_get_tool.prompt import DESCRIPTION, PROMPT, TASK_GET_TOOL_NAME
from optimus.utils.tasks import get_task, get_task_list_id, is_todo_v2_enabled

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "taskId": {"type": "string", "description": "The ID of the task to retrieve"},
    },
    "required": ["taskId"],
    "additionalProperties": False,
}


@build_tool
class TaskGetTool:
    name = TASK_GET_TOOL_NAME
    search_hint = "retrieve a task by ID"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return "TaskGet"

    def is_enabled(self) -> bool:
        return is_todo_v2_enabled()

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("taskId", "")

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        return ValidationResult.ok()

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        task = await get_task(get_task_list_id(), input["taskId"])
        if not task:
            return ToolResult(data={"task": None})
        return ToolResult(data={
            "task": {
                "id": task["id"],
                "subject": task["subject"],
                "description": task["description"],
                "status": task["status"],
                "blocks": task.get("blocks", []),
                "blockedBy": task.get("blockedBy", []),
            },
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        task = data.get("task")
        if not task:
            # Non-error: benign condition the model can handle.
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": "Task not found"}

        lines = [
            f"Task #{task['id']}: {task['subject']}",
            f"Status: {task['status']}",
            f"Description: {task['description']}",
        ]
        if task["blockedBy"]:
            lines.append("Blocked by: " + ", ".join(f"#{i}" for i in task["blockedBy"]))
        if task["blocks"]:
            lines.append("Blocks: " + ", ".join(f"#{i}" for i in task["blocks"]))
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": "\n".join(lines)}
