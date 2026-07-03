"""tools/send_message_tool/send_message_tool.py — port of src/tools/SendMessageTool
(restored from commit f696afe, upgraded to the current Tool protocol)."""
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
from optimus.tools.send_message_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    SEND_MESSAGE_TOOL_NAME,
)
from optimus.utils.swarm.mailbox import write_to_mailbox

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "description": "Agent ID or name to send the message to"},
        "message": {"type": "string", "description": "The message content to send"},
        "message_type": {
            "type": "string",
            "enum": ["text", "shutdown_request", "shutdown_response", "plan_approval_response"],
            "description": "Type of message (default: text)",
        },
        "request_id": {"type": "string", "description": "Request ID for response messages"},
        "approve": {"type": "boolean", "description": "For shutdown_response / plan_approval_response"},
    },
    "required": ["to", "message"],
    "additionalProperties": False,
}


@build_tool
class SendMessageTool:
    name = SEND_MESSAGE_TOOL_NAME
    search_hint = "message another agent in the swarm"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 20_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True  # in-process queue write, no external effect

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return f"to {input.get('to', '')}"

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("to", "").strip():
            return ValidationResult.fail("to must not be empty", error_code=1)
        message_type = input.get("message_type", "text")
        if message_type.endswith("_response") and not input.get("request_id"):
            return ValidationResult.fail(
                f"request_id is required for {message_type} messages", error_code=2
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
        payload: dict[str, Any] = {
            "type": input.get("message_type", "text"),
            "content": input["message"],
            "from": context.agent_id or "main",
        }
        if input.get("request_id") is not None:
            payload["request_id"] = input["request_id"]
        if input.get("approve") is not None:
            payload["approve"] = input["approve"]

        try:
            await write_to_mailbox(input["to"], payload)
            return ToolResult(data={"delivered": True, "to": input["to"],
                                    "message_type": payload["type"]})
        except Exception as exc:
            return ToolResult(data={"delivered": False, "to": input["to"], "error": str(exc)})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if not data.get("delivered"):
            return {"type": "tool_result",
                    "content": f"Failed to deliver message to {data['to']}: {data.get('error')}",
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result",
                "content": f"Message ({data['message_type']}) delivered to {data['to']}.",
                "tool_use_id": tool_use_id}
