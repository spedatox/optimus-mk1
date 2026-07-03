"""tools/task_list_tool/task_list_tool.py — port of
src/tools/TaskListTool/TaskListTool.ts (verified against source)."""
from __future__ import annotations

from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.task_list_tool.prompt import (
    DESCRIPTION,
    TASK_LIST_TOOL_NAME,
    get_prompt,
)
from optimus.utils.tasks import get_task_list_id, is_todo_v2_enabled, list_tasks

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@build_tool
class TaskListTool:
    name = TASK_LIST_TOOL_NAME
    search_hint = "list all tasks"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_prompt()

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return "TaskList"

    def is_enabled(self) -> bool:
        return is_todo_v2_enabled()

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
        all_tasks = [
            t for t in await list_tasks(get_task_list_id())
            if not (t.get("metadata") or {}).get("_internal")
        ]

        # Resolved blockers are dropped from blockedBy so the list shows only
        # OPEN dependencies.
        resolved = {t["id"] for t in all_tasks if t["status"] == "completed"}
        tasks = [
            {
                "id": t["id"],
                "subject": t["subject"],
                "status": t["status"],
                "owner": t.get("owner"),
                "blockedBy": [i for i in t.get("blockedBy", []) if i not in resolved],
            }
            for t in all_tasks
        ]
        return ToolResult(data={"tasks": tasks})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        tasks = data.get("tasks", [])
        if not tasks:
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": "No tasks found"}

        lines = []
        for task in tasks:
            owner = f" ({task['owner']})" if task.get("owner") else ""
            blocked = (
                " [blocked by " + ", ".join(f"#{i}" for i in task["blockedBy"]) + "]"
                if task["blockedBy"]
                else ""
            )
            lines.append(f"#{task['id']} [{task['status']}] {task['subject']}{owner}{blocked}")
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": "\n".join(lines)}
