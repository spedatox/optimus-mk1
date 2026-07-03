"""tools/exit_plan_mode_tool/exit_plan_mode_tool.py — port of
src/tools/ExitPlanModeTool (restored from commit f696afe, upgraded to the
current Tool protocol).

Companion to EnterPlanModeTool: presents the plan for user approval and, once
approved, flips the permission mode back so file edits and shell commands
execute normally again.

Porting notes:
  - The TS approval dialog (PlanApprovalDialog React component) → the
    check_permissions 'ask' behavior; the query loop's can_use_tool gate is the
    approval UI (PermissionModal in the TUI, stdin prompt headless).
  - Mode restore: pre_plan_mode from the permission context when set (recorded
    by EnterPlanModeTool), else 'default'. handle_plan_mode_transition drives
    the bootstrap-state plan-mode attachments exactly as on entry.
  - feature('PLAN_MODE_V2_INTERVIEW') / launchSubagents → omitted (feature off).
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
from optimus.bootstrap.state import handle_plan_mode_transition
from optimus.tools.exit_plan_mode_tool.prompt import (
    DESCRIPTION,
    EXIT_PLAN_MODE_TOOL_NAME,
    PROMPT,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "string",
            "description": (
                "The implementation plan to present to the user for approval. "
                "Supports markdown. Should be concise and concrete."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}

EXITED_MESSAGE = (
    "User has approved your plan. You can now start coding. Start with updating "
    "your todo list if applicable."
)


@build_tool
class ExitPlanModeTool:
    """Presents the plan for approval and exits plan mode."""

    name = EXIT_PLAN_MODE_TOOL_NAME
    search_hint = "present the plan and exit plan mode to start coding"
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
        return ""

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def requires_user_interaction(self) -> bool:
        # Plan approval always goes through the user.
        return True

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        # 'ask' surfaces the plan through the permission gate — approving the
        # tool call IS approving the plan (mirrors the TS approval dialog).
        return PermissionResult(
            behavior="ask",
            updated_input=input,
            message="Would you like to proceed with this plan?",
        )

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        ctx_tpc = context.tool_permission_context
        prev_mode = getattr(ctx_tpc, "mode", "plan")
        restored_mode = getattr(ctx_tpc, "pre_plan_mode", None) or "default"

        # Mark the transition in bootstrap state (clears plan-mode attachments).
        handle_plan_mode_transition(prev_mode, restored_mode)

        # Apply the mode flip — prefer set_app_state, fall back to mutating the
        # context's permission context (same strategy as EnterPlanModeTool).
        if context.set_app_state is not None:
            def _mutate(prev: Any) -> Any:
                if isinstance(prev, dict):
                    tpc = dict(prev.get("toolPermissionContext", {}))
                    tpc["mode"] = restored_mode
                    tpc.pop("prePlanMode", None)
                    return {**prev, "toolPermissionContext": tpc}
                return prev
            context.set_app_state(_mutate)
        if ctx_tpc is not None:
            ctx_tpc.mode = restored_mode
            ctx_tpc.pre_plan_mode = None

        return ToolResult(data={"plan": input.get("plan", ""), "message": EXITED_MESSAGE})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        message = data["message"] if isinstance(data, dict) else str(data)
        return {"type": "tool_result", "content": message, "tool_use_id": tool_use_id}
