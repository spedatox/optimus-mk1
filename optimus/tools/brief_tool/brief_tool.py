"""tools/brief_tool/brief_tool.py — port of src/tools/BriefTool (restored from
commit f696afe, upgraded to the current Tool protocol).

Delivers a user-facing status message. In the TUI the message is routed to
add_notification / append_system_message when wired; the tool result records
the delivery either way so the transcript shows what was sent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.brief_tool.prompt import BRIEF_TOOL_NAME, DESCRIPTION, PROMPT

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "The message for the user. Supports markdown formatting.",
        },
        "attachments": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional file paths to attach alongside the message",
        },
        "status": {
            "type": "string",
            "enum": ["normal", "proactive"],
            "description": (
                "Use 'proactive' for unsolicited status updates or blockers. "
                "Use 'normal' when replying to something the user just said."
            ),
        },
    },
    "required": ["message", "status"],
    "additionalProperties": False,
}


@build_tool
class BriefTool:
    name = BRIEF_TOOL_NAME
    search_hint = "send the user a status update message"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 50_000
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

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("message", "").strip():
            return ValidationResult.fail("message must not be empty", error_code=1)
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
        message: str = input["message"]
        status: str = input.get("status", "normal")

        resolved_attachments = []
        for path_str in input.get("attachments") or []:
            p = Path(path_str)
            if p.exists():
                resolved_attachments.append({
                    "path": str(p.resolve()),
                    "size": p.stat().st_size,
                    "isImage": p.suffix.lower() in _IMAGE_SUFFIXES,
                })

        # Route into the UI when the session wires a channel for it.
        delivered_via = "transcript"
        if context.add_notification is not None:
            try:
                context.add_notification(message)
                delivered_via = "notification"
            except Exception:
                pass
        if status == "proactive" and context.send_os_notification is not None:
            try:
                context.send_os_notification(message)
            except Exception:
                pass

        return ToolResult(data={
            "message": message,
            "status": status,
            "attachments": resolved_attachments or None,
            "deliveredVia": delivered_via,
            "sentAt": datetime.now(timezone.utc).isoformat(),
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        n = len(data.get("attachments") or [])
        suffix = f" with {n} attachment(s)" if n else ""
        return {
            "type": "tool_result",
            "content": f"Message delivered to the user ({data['status']}){suffix}.",
            "tool_use_id": tool_use_id,
        }
