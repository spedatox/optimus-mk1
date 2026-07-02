"""
tools/todo_write_tool/todo_write_tool.py — port of src/tools/TodoWriteTool/TodoWriteTool.ts

Maintains a structured, session-scoped task list. Each item has content
(imperative), activeForm (present continuous), and status (pending |
in_progress | completed).

Porting notes:
  - appState.todos[key] → bootstrap state todo store (get_todos/set_todos),
    keyed by agent_id ?? session_id.
  - When the whole list is completed the stored list is cleared (matches TS).
  - feature('VERIFICATION_AGENT') nudge → omitted (feature off).
  - isTodoV2 gating → is_enabled returns True (V2 off).
"""
from __future__ import annotations

from typing import Any, Optional

from optimus.bootstrap.state import get_session_id, get_todos, set_todos
from optimus.Tool import PermissionResult, ToolResult, ToolUseContext, ValidationResult, build_tool
from optimus.tools.todo_write_tool.prompt import DESCRIPTION, PROMPT, TODO_WRITE_TOOL_NAME

_TODO_ITEM = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "Imperative form, e.g. 'Run tests'"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
        "activeForm": {"type": "string", "description": "Present continuous form, e.g. 'Running tests'"},
    },
    "required": ["content", "status", "activeForm"],
    "additionalProperties": False,
}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {"type": "array", "items": _TODO_ITEM, "description": "The updated todo list"},
    },
    "required": ["todos"],
    "additionalProperties": False,
}


@build_tool
class TodoWriteTool:
    name = TODO_WRITE_TOOL_NAME
    search_hint = "manage the session task checklist"
    max_result_size_chars = 100_000
    strict = True
    should_defer = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return ""

    def is_read_only(self, input: dict[str, Any]) -> bool:
        # Updates session state, not the filesystem — safe/concurrency-neutral.
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return f"{len(input.get('todos', []))} items"

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        for item in input.get("todos", []):
            if not item.get("content"):
                return ValidationResult.fail("Content cannot be empty", error_code=1)
            if not item.get("activeForm"):
                return ValidationResult.fail("Active form cannot be empty", error_code=2)
            if item.get("status") not in ("pending", "in_progress", "completed"):
                return ValidationResult.fail("Invalid status", error_code=3)
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
        todos = input["todos"]
        todo_key = context.agent_id or get_session_id()
        old_todos = get_todos(todo_key)
        all_done = len(todos) > 0 and all(t["status"] == "completed" for t in todos)
        new_todos = [] if all_done else todos
        set_todos(todo_key, new_todos)
        return ToolResult(data={"oldTodos": old_todos, "newTodos": todos})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        content = (
            "Todos have been modified successfully. Ensure that you continue to use the "
            "todo list to track your progress. Please proceed with the current tasks if applicable"
        )
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
