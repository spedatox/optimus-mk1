"""tools/task_output_tool/task_output_tool.py — port of src/tools/TaskOutputTool
(restored from commit f696afe, upgraded to the current Tool protocol)."""
from __future__ import annotations

import asyncio
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
from optimus.tools.task_output_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    TASK_OUTPUT_TOOL_NAME,
)

_TERMINAL_STATUSES = ("completed", "failed", "stopped")

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "The task ID to get output from"},
        "block": {"type": "boolean", "description": "Whether to wait for task completion (default true)"},
        "timeout": {"type": "number", "description": "Max wait time in ms, 0-600000 (default 30000)"},
    },
    "required": ["task_id"],
    "additionalProperties": False,
}


def _task_summary(task_id: str, task: Any, output: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_type": task.task_type,
        "status": task.status,
        "description": task.description,
        "output": output,
        "exitCode": getattr(task, "exit_code", None),
        "error": getattr(task, "error", None),
    }


@build_tool
class TaskOutputTool:
    name = TASK_OUTPUT_TOOL_NAME
    aliases = ["BashOutput"]
    search_hint = "read output of a background task or shell"
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

    def interrupt_behavior(self) -> str:
        return "cancel"  # cancelling the wait must not kill the watched task

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("task_id", "").strip():
            return ValidationResult.fail("task_id must not be empty", error_code=1)
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
        task_id: str = input["task_id"]
        block: bool = input.get("block", True)
        timeout_s = min(max(float(input.get("timeout", 30000)) / 1000.0, 0.0), 600.0)

        task = get_task_registry().get(task_id)
        if task is None:
            return ToolResult(data={"retrieval_status": "not_found", "task_id": task_id, "task": None})

        if block and task.status not in _TERMINAL_STATUSES:
            try:
                await asyncio.wait_for(task.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                return ToolResult(data={
                    "retrieval_status": "timeout",
                    "task": _task_summary(task_id, task, task.get_partial_output()),
                })

        if task.status in _TERMINAL_STATUSES:
            output = await task.get_output()
        else:
            output = task.get_partial_output()
        return ToolResult(data={
            "retrieval_status": "success",
            "task": _task_summary(task_id, task, output),
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("retrieval_status") == "not_found":
            return {"type": "tool_result", "content": f"Task not found: {data['task_id']}",
                    "tool_use_id": tool_use_id, "is_error": True}
        task = data["task"]
        header = f"[{task['status']}] {task['task_type']}: {task['description']}"
        if data["retrieval_status"] == "timeout":
            header += " (wait timed out — task still running)"
        content = f"{header}\n\n{task.get('output') or '(no output yet)'}"
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
