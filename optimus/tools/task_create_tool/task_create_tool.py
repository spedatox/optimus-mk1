"""tools/task_create_tool/task_create_tool.py — port of
src/tools/TaskCreateTool/TaskCreateTool.ts (verified against source).

Porting notes:
  - executeTaskCreatedHooks → RE-ENTRY (hooks system not ported); the
    blocking-error rollback branch plugs in there.
  - context.setAppState auto-expand of the tasks panel is applied when the
    session wires set_app_state.
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
from optimus.tools.task_create_tool.prompt import (
    DESCRIPTION,
    TASK_CREATE_TOOL_NAME,
    get_prompt,
)
from optimus.utils.tasks import create_task, get_task_list_id, is_todo_v2_enabled

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "A brief title for the task"},
        "description": {"type": "string", "description": "What needs to be done"},
        "activeForm": {
            "type": "string",
            "description": 'Present continuous form shown in spinner when in_progress (e.g., "Running tests")',
        },
        "metadata": {"type": "object", "description": "Arbitrary metadata to attach to the task"},
    },
    "required": ["subject", "description"],
    "additionalProperties": False,
}

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "subject": {"type": "string"}},
            "required": ["id", "subject"],
        },
    },
    "required": ["task"],
}


@build_tool
class TaskCreateTool:
    name = TASK_CREATE_TOOL_NAME
    search_hint = "create a task in the task list"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    output_schema = _OUTPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_prompt()

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return "TaskCreate"

    def is_enabled(self) -> bool:
        return is_todo_v2_enabled()

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("subject", "")

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
        task_id = await create_task(get_task_list_id(), {
            "subject": input["subject"],
            "description": input["description"],
            "activeForm": input.get("activeForm"),
            "status": "pending",
            "owner": None,
            "blocks": [],
            "blockedBy": [],
            "metadata": input.get("metadata"),
        })

        # RE-ENTRY: executeTaskCreatedHooks — blocking hook errors delete the
        # task and raise, once the hooks system is ported.

        # Auto-expand task list when creating tasks.
        if context.set_app_state is not None:
            def _expand(prev: Any) -> Any:
                if isinstance(prev, dict) and prev.get("expandedView") != "tasks":
                    return {**prev, "expandedView": "tasks"}
                return prev
            context.set_app_state(_expand)

        return ToolResult(data={"task": {"id": task_id, "subject": input["subject"]}})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        task = data["task"]
        return {
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": f"Task #{task['id']} created successfully: {task['subject']}",
        }
