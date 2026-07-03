"""tools/remote_trigger_tool/remote_trigger_tool.py — port of
src/tools/RemoteTriggerTool (restored from commit f696afe, upgraded to the
current Tool protocol; uses httpx which is already a project dependency, and
the oauth bearer token from optimus.api for authentication)."""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.remote_trigger_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    REMOTE_TRIGGER_TOOL_NAME,
)

_TRIGGERS_BETA = "ccr-triggers-2026-01-30"
_ACTIONS_NEEDING_ID = {"get", "update", "run"}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "get", "create", "update", "run"],
            "description": "Action to perform",
        },
        "trigger_id": {"type": "string", "description": "Required for get, update, and run"},
        "body": {"type": "object", "description": "JSON body for create and update"},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def _base_url() -> str:
    return os.environ.get("CLAUDE_AI_API_URL", "https://api.claude.ai")


@build_tool
class RemoteTriggerTool:
    name = REMOTE_TRIGGER_TOOL_NAME
    search_hint = "manage remote scheduled agent triggers"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return (input or {}).get("action") in ("list", "get")

    def is_open_world(self, input: dict[str, Any]) -> bool:
        return True

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        action = input.get("action")
        if action in _ACTIONS_NEEDING_ID and not input.get("trigger_id"):
            return ValidationResult.fail(f"trigger_id is required for '{action}'", error_code=1)
        if action in ("create", "update") and not input.get("body"):
            return ValidationResult.fail(f"body is required for '{action}'", error_code=2)
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        if input.get("action") in ("list", "get"):
            return PermissionResult(behavior="allow", updated_input=input)
        # Mutating a remote trigger is outward-facing — confirm.
        return PermissionResult(
            behavior="ask", updated_input=input,
            message=f"Perform remote trigger action '{input.get('action')}'?",
        )

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        import httpx

        from optimus.api import _get_oauth_access_token

        action: str = input["action"]
        trigger_id: Optional[str] = input.get("trigger_id")
        body: Optional[dict] = input.get("body")

        base = f"{_base_url()}/api/triggers"
        routes = {
            "list": (base, "GET"),
            "get": (f"{base}/{trigger_id}", "GET"),
            "create": (base, "POST"),
            "update": (f"{base}/{trigger_id}", "PUT"),
            "run": (f"{base}/{trigger_id}/run", "POST"),
        }
        url, method = routes[action]

        headers = {"anthropic-beta": _TRIGGERS_BETA}
        token = _get_oauth_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req_kwargs: dict[str, Any] = {"headers": headers}
        if body and method in ("POST", "PUT"):
            req_kwargs["json"] = body

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(method, url, **req_kwargs)
        except Exception as exc:
            return ToolResult(data={"error": f"Request failed: {exc}"})

        try:
            payload: Any = resp.json()
        except Exception:
            payload = resp.text
        return ToolResult(data={"status": resp.status_code, "response": payload})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        content = json.dumps(data, default=str)
        block: dict[str, Any] = {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
        if data.get("status", 200) >= 400:
            block["is_error"] = True
        return block
