"""tools/task_update_tool/task_update_tool.py — port of
src/tools/TaskUpdateTool/TaskUpdateTool.ts (verified against source).

Porting notes:
  - executeTaskCompletedHooks → RE-ENTRY (hooks system not ported); the
    blocking-error branch that refuses completion plugs in there.
  - feature('VERIFICATION_AGENT') verification nudge → omitted (feature off).
  - Teammate mailbox notification on owner change is kept (swarm utils exist);
    getAgentName/getTeammateColor → context.agent_id / None until
    utils/teammate.ts is ported.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.task_update_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    TASK_UPDATE_TOOL_NAME,
)
from optimus.utils.tasks import (
    TASK_STATUSES,
    block_task,
    delete_task,
    get_task,
    get_task_list_id,
    is_agent_swarms_enabled,
    is_todo_v2_enabled,
    update_task,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "taskId": {"type": "string", "description": "The ID of the task to update"},
        "subject": {"type": "string", "description": "New subject for the task"},
        "description": {"type": "string", "description": "New description for the task"},
        "activeForm": {
            "type": "string",
            "description": 'Present continuous form shown in spinner when in_progress (e.g., "Running tests")',
        },
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "completed", "deleted"],
            "description": "New status for the task",
        },
        "addBlocks": {"type": "array", "items": {"type": "string"},
                      "description": "Task IDs that this task blocks"},
        "addBlockedBy": {"type": "array", "items": {"type": "string"},
                         "description": "Task IDs that block this task"},
        "owner": {"type": "string", "description": "New owner for the task"},
        "metadata": {
            "type": "object",
            "description": "Metadata keys to merge into the task. Set a key to null to delete it.",
        },
    },
    "required": ["taskId"],
    "additionalProperties": False,
}


@build_tool
class TaskUpdateTool:
    name = TASK_UPDATE_TOOL_NAME
    search_hint = "update a task"
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
        return "TaskUpdate"

    def is_enabled(self) -> bool:
        return is_todo_v2_enabled()

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        parts = [input.get("taskId", "")]
        if input.get("status"):
            parts.append(input["status"])
        if input.get("subject"):
            parts.append(input["subject"])
        return " ".join(parts)

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        status = input.get("status")
        if status is not None and status not in (*TASK_STATUSES, "deleted"):
            return ValidationResult.fail(f"Invalid status: {status}", error_code=1)
        return ValidationResult.ok()

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        task_list_id = get_task_list_id()
        task_id: str = input["taskId"]

        # Auto-expand task list when updating tasks.
        if context.set_app_state is not None:
            def _expand(prev: Any) -> Any:
                if isinstance(prev, dict) and prev.get("expandedView") != "tasks":
                    return {**prev, "expandedView": "tasks"}
                return prev
            context.set_app_state(_expand)

        existing = await get_task(task_list_id, task_id)
        if not existing:
            return ToolResult(data={
                "success": False, "taskId": task_id, "updatedFields": [],
                "error": "Task not found",
            })

        updated_fields: list[str] = []
        updates: dict[str, Any] = {}

        for field in ("subject", "description", "activeForm", "owner"):
            if field in input and input[field] != existing.get(field):
                updates[field] = input[field]
                updated_fields.append(field)

        # Auto-set owner when a teammate marks a task in_progress without one.
        if (
            is_agent_swarms_enabled()
            and input.get("status") == "in_progress"
            and "owner" not in input
            and not existing.get("owner")
            and context.agent_id
        ):
            updates["owner"] = context.agent_id
            updated_fields.append("owner")

        if "metadata" in input and input["metadata"] is not None:
            merged = dict(existing.get("metadata") or {})
            for key, value in input["metadata"].items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
            updates["metadata"] = merged
            updated_fields.append("metadata")

        status = input.get("status")
        if status is not None:
            if status == "deleted":
                deleted = await delete_task(task_list_id, task_id)
                return ToolResult(data={
                    "success": deleted,
                    "taskId": task_id,
                    "updatedFields": ["deleted"] if deleted else [],
                    "error": None if deleted else "Failed to delete task",
                    "statusChange": {"from": existing["status"], "to": "deleted"} if deleted else None,
                })
            if status != existing["status"]:
                # RE-ENTRY: executeTaskCompletedHooks on status == 'completed' —
                # blocking hook errors refuse the completion.
                updates["status"] = status
                updated_fields.append("status")

        if updates:
            await update_task(task_list_id, task_id, updates)

        # Notify the new owner via mailbox when ownership changes (swarms).
        if updates.get("owner") and is_agent_swarms_enabled():
            from optimus.utils.swarm.mailbox import write_to_mailbox

            sender = context.agent_id or "team-lead"
            await write_to_mailbox(updates["owner"], {
                "from": sender,
                "text": json.dumps({
                    "type": "task_assignment",
                    "taskId": task_id,
                    "subject": existing["subject"],
                    "description": existing["description"],
                    "assignedBy": sender,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Dependencies: this task blocks others / others block this one.
        new_blocks = [i for i in input.get("addBlocks") or [] if i not in existing.get("blocks", [])]
        for block_id in new_blocks:
            await block_task(task_list_id, task_id, block_id)
        if new_blocks:
            updated_fields.append("blocks")

        new_blocked_by = [
            i for i in input.get("addBlockedBy") or [] if i not in existing.get("blockedBy", [])
        ]
        for blocker_id in new_blocked_by:
            await block_task(task_list_id, blocker_id, task_id)
        if new_blocked_by:
            updated_fields.append("blockedBy")

        # feature('VERIFICATION_AGENT') nudge → omitted (feature off).

        return ToolResult(data={
            "success": True,
            "taskId": task_id,
            "updatedFields": updated_fields,
            "statusChange": (
                {"from": existing["status"], "to": updates["status"]}
                if "status" in updates else None
            ),
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if not data.get("success"):
            # Non-error so it doesn't trigger sibling tool cancellation —
            # "Task not found" is benign and the model can handle it.
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": data.get("error") or f"Task #{data['taskId']} not found",
            }

        content = f"Updated task #{data['taskId']} {', '.join(data['updatedFields'])}"
        status_change = data.get("statusChange")
        if status_change and status_change["to"] == "completed" and is_agent_swarms_enabled():
            content += (
                "\n\nTask completed. Call TaskList now to find your next available "
                "task or see if your work unblocked others."
            )
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
