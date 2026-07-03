"""tools/synthetic_output_tool/synthetic_output_tool.py — port of
src/tools/SyntheticOutputTool (restored from commit f696afe, upgraded to the
current Tool protocol).

Used by SDK/headless callers that request structured output: the caller
supplies an output schema (via context.options or set_output_schema), the
model calls this tool once with a matching payload, and the payload is passed
through verbatim (validated when the schema is available).

Validation uses jsonschema when installed; otherwise a shape check on
required top-level properties (documented in PORTING_NOTES.md).
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
from optimus.tools.synthetic_output_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    SYNTHETIC_OUTPUT_TOOL_NAME,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Structured output — any JSON object matching the requested schema.",
    "additionalProperties": True,
}

# Session-scoped output schema, set by the headless/SDK entrypoint when the
# caller requests structured output.
_output_schema: Optional[dict[str, Any]] = None


def set_output_schema(schema: Optional[dict[str, Any]]) -> None:
    global _output_schema
    _output_schema = schema


def get_output_schema() -> Optional[dict[str, Any]]:
    return _output_schema


def _validate_against_schema(payload: dict[str, Any], schema: dict[str, Any]) -> Optional[str]:
    """Return an error string if the payload does not match, else None."""
    try:
        import jsonschema

        jsonschema.validate(payload, schema)
        return None
    except ImportError:
        # Degraded check: required top-level properties must be present.
        missing = [k for k in schema.get("required", []) if k not in payload]
        if missing:
            return f"Missing required properties: {', '.join(missing)}"
        return None
    except Exception as exc:
        return str(exc)


@build_tool
class SyntheticOutputTool:
    name = SYNTHETIC_OUTPUT_TOOL_NAME
    search_hint = "emit the final structured output payload"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 200_000

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_enabled(self) -> bool:
        # Only offered when a caller registered an output schema.
        return _output_schema is not None

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if _output_schema is not None:
            error = _validate_against_schema(input, _output_schema)
            if error:
                return ValidationResult.fail(f"Output does not match the requested schema: {error}", error_code=1)
        return ValidationResult.ok()

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        return ToolResult(data={"output": input})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "content": json.dumps(data.get("output", {}), default=str),
            "tool_use_id": tool_use_id,
        }
