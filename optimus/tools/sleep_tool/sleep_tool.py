"""tools/sleep_tool/sleep_tool.py — port of src/tools/SleepTool (restored from
commit f696afe, upgraded to the current Tool protocol).

asyncio-based wait that honours the abort signal: the sleep is chopped into
short slices so an interrupt (abort_controller set) takes effect within 100ms
instead of holding until the full duration elapses.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.sleep_tool.prompt import DESCRIPTION, PROMPT, SLEEP_TOOL_NAME

MAX_SLEEP_SECONDS = 300.0  # 5 minutes, mirrors the source cap
_SLICE_SECONDS = 0.1

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "duration": {
            "type": "number",
            "description": f"Duration to sleep in seconds (max {int(MAX_SLEEP_SECONDS)}).",
        },
    },
    "required": ["duration"],
    "additionalProperties": False,
}


@build_tool
class SleepTool:
    """Waits for a duration; interruptible."""

    name = SLEEP_TOOL_NAME
    search_hint = "wait or pause for a duration"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 10_000
    strict = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def interrupt_behavior(self) -> str:
        return "cancel"

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return f"{input.get('duration', 0)}s"

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        duration = input.get("duration")
        if not isinstance(duration, (int, float)) or duration < 0:
            return ValidationResult.fail("duration must be a non-negative number", error_code=1)
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
        duration = max(0.0, min(float(input["duration"]), MAX_SLEEP_SECONDS))
        slept = 0.0
        interrupted = False
        while slept < duration:
            if context.abort_controller is not None and context.abort_controller.is_set():
                interrupted = True
                break
            step = min(_SLICE_SECONDS, duration - slept)
            await asyncio.sleep(step)
            slept += step
        return ToolResult(data={"sleptSeconds": round(slept, 1), "interrupted": interrupted})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("interrupted"):
            content = f"Sleep interrupted after {data['sleptSeconds']}s."
        else:
            content = f"Slept for {data['sleptSeconds']}s."
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
