"""tools/config_tool/config_tool.py — port of src/tools/ConfigTool (restored
from commit f696afe, upgraded to the current Tool protocol and wired to the
real config module).

Reads and writes the global config through utils/config.py
(get_global_config / save_global_config), so writes go through the locked,
backed-up, auth-guarded save path rather than raw file IO.
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
from optimus.tools.config_tool.prompt import CONFIG_TOOL_NAME, DESCRIPTION, PROMPT
from optimus.utils.config import get_global_config, save_global_config

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "setting": {
            "type": "string",
            "description": 'The setting key, dot-separated for nested keys (e.g. "theme", "env.DEBUG").',
        },
        "value": {
            "description": "The new value. Omit to read the current value.",
        },
    },
    "required": ["setting"],
    "additionalProperties": False,
}

# Keys the model may not touch — auth/identity state.
_PROTECTED_KEYS = {"oauthAccount", "primaryApiKey", "userID", "customApiKeyResponses"}


def _resolve(config: dict[str, Any], keys: list[str]) -> Any:
    current: Any = config
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return None
    return current


@build_tool
class ConfigTool:
    name = CONFIG_TOOL_NAME
    search_hint = "read or change optimus settings"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 50_000
    strict = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return "value" not in (input or {})

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return "value" not in (input or {})

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("setting", "")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        setting = input.get("setting", "")
        if not setting.strip():
            return ValidationResult.fail("setting must not be empty", error_code=1)
        if setting.split(".")[0] in _PROTECTED_KEYS:
            return ValidationResult.fail(
                f"Setting '{setting}' is protected and cannot be modified via the Config tool.",
                error_code=2,
            )
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        if "value" in input:
            # Writes prompt by default — config changes outlive the session.
            return PermissionResult(
                behavior="ask", updated_input=input,
                message=f"Change setting '{input.get('setting')}'?",
            )
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        setting: str = input["setting"]
        keys = setting.split(".")
        config = get_global_config()
        current = _resolve(config, keys)

        if "value" not in input:
            return ToolResult(data={
                "operation": "get", "setting": setting, "value": current, "success": True,
            })

        value = input["value"]

        def _update(cfg: dict[str, Any]) -> dict[str, Any]:
            new_cfg = {**cfg}
            obj = new_cfg
            for k in keys[:-1]:
                child = obj.get(k)
                obj[k] = dict(child) if isinstance(child, dict) else {}
                obj = obj[k]
            obj[keys[-1]] = value
            return new_cfg

        try:
            save_global_config(_update)
        except Exception as exc:
            return ToolResult(data={
                "operation": "set", "setting": setting, "success": False, "error": str(exc),
            })

        return ToolResult(data={
            "operation": "set",
            "setting": setting,
            "previousValue": current,
            "newValue": value,
            "success": True,
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "content": json.dumps(data, default=str),
            "tool_use_id": tool_use_id,
        }
        if not data.get("success", True):
            block["is_error"] = True
        return block
