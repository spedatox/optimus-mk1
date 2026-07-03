"""tools/enter_plan_mode_tool/enter_plan_mode_tool.py — port of
src/tools/EnterPlanModeTool/EnterPlanModeTool.ts.

Transitions into plan mode (a read-only exploration + design phase).
The model calls this when it wants to design an implementation approach and
get user sign-off before writing code.

Porting notes:
  - React render fns (renderToolUseMessage / renderToolResultMessage /
    renderToolUseRejectedMessage) → return None (no UI layer); the TUI has its
    own plan-mode indicators in the status bar.
  - feature('KAIROS'/'KAIROS_CHANNELS') → False, so getAllowedChannels gate →
    is_enabled always True (matches the non-feature-gated flavor).
  - isPlanModeInterviewPhaseEnabled() → False (feature off); the plan-mode
    workflow instructions are always emitted (non-interview external flavor).
  - prepareContextForPlanMode / applyPermissionUpdate classifier side-effects
    are feature('TRANSCRIPT_CLASSIFIER')-gated in the source → dropped here;
    only the mode flip itself is applied. RE-ENTRY: classifier activation when
    defaultMode is 'auto' is wired in permissionSetup.ts (not yet ported).
  - context.setAppState is optional; when absent we update
    context.tool_permission_context.mode directly so the mode change still
    takes effect for the rest of the turn.
  - context.agentId throws (matches the source's guard against agent contexts).
"""
from __future__ import annotations

from typing import Any

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.bootstrap.state import handle_plan_mode_transition
from optimus.tools.enter_plan_mode_tool.constants import ENTER_PLAN_MODE_TOOL_NAME
from optimus.tools.enter_plan_mode_tool.prompt import get_enter_plan_mode_tool_prompt


# ---------------------------------------------------------------------------
# JSON schemas (mirror the Zod schemas)
# ---------------------------------------------------------------------------

# z.strictObject({}) — no parameters.
INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "Confirmation that plan mode was entered",
        },
    },
    "required": ["message"],
    "additionalProperties": False,
}

ENTERED_MESSAGE = (
    "Entered plan mode. You should now focus on exploring the codebase "
    "and designing an implementation approach."
)


@build_tool
class EnterPlanModeTool:
    """Requests permission to enter plan mode for complex tasks needing design."""

    name = ENTER_PLAN_MODE_TOOL_NAME
    aliases: list[str] = []
    search_hint = "switch to plan mode to design an approach before coding"
    input_schema = INPUT_SCHEMA
    input_json_schema = INPUT_SCHEMA
    output_schema = OUTPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    is_mcp = False
    is_lsp = False
    should_defer = True
    always_load = False
    mcp_info = None

    async def description(self, input: dict[str, Any], options: dict[str, Any]) -> str:
        return (
            "Requests permission to enter plan mode for complex tasks requiring "
            "exploration and design"
        )

    async def prompt(self, options: dict[str, Any]) -> str:
        return get_enter_plan_mode_tool_prompt()

    def user_facing_name(self, input: dict[str, Any] | None) -> str:
        return ""

    def is_enabled(self) -> bool:
        # feature('KAIROS') || feature('KAIROS_CHANNELS') → False, so the
        # channels-gate never disables the tool.
        return True

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def is_destructive(self, input: dict[str, Any]) -> bool:
        return False

    async def validate_input(
        self, input: dict[str, Any], context: ToolUseContext
    ) -> ValidationResult:
        return ValidationResult.ok()

    async def check_permissions(
        self, input: dict[str, Any], context: ToolUseContext
    ) -> PermissionResult:
        # Entering plan mode is a low-risk mode switch; the source returns the
        # default allow + the call() drives the mode transition itself.
        return PermissionResult(behavior="allow", updated_input=input)

    def requires_user_interaction(self) -> bool:
        return False

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any,
        parent_message: dict[str, Any],
        on_progress: Any = None,
    ) -> ToolResult:
        if context.agent_id:
            raise Exception("EnterPlanMode tool cannot be used in agent contexts")

        app_state = context.get_app_state() if context.get_app_state else None
        prev_mode = (
            app_state.get("toolPermissionContext", {}).get("mode", "default")
            if isinstance(app_state, dict)
            else getattr(getattr(context, "tool_permission_context", None), "mode", "default")
        )

        # Mark the transition in bootstrap state (drives plan-mode attachments).
        handle_plan_mode_transition(prev_mode, "plan")

        # Apply the mode flip. Prefer set_app_state (REPL/headless wires it);
        # fall back to mutating the context's permission context so the change
        # still takes effect for this turn.
        if context.set_app_state is not None:
            def _mutate(prev: Any) -> Any:
                if isinstance(prev, dict):
                    tpc = dict(prev.get("toolPermissionContext", {}))
                    tpc["mode"] = "plan"
                    if "prePlanMode" not in tpc:
                        tpc["prePlanMode"] = tpc.get("pre_plan_mode", prev_mode)
                    return {**prev, "toolPermissionContext": tpc}
                return prev
            context.set_app_state(_mutate)
        else:
            ctx_tpc = context.tool_permission_context
            if ctx_tpc is not None:
                ctx_tpc.mode = "plan"
                if ctx_tpc.pre_plan_mode is None:
                    ctx_tpc.pre_plan_mode = prev_mode

        return ToolResult(data={"message": ENTERED_MESSAGE})

    def map_tool_result_to_tool_result_block_param(
        self, content: Any, tool_use_id: str
    ) -> dict[str, Any]:
        # feature('PLAN_MODE_V2_INTERVIEW') → False → always emit the
        # non-interview workflow instructions (matches external flavor).
        message = content["message"] if isinstance(content, dict) else str(content)
        instructions = (
            f"{message}\n\n"
            "In plan mode, you should:\n"
            "1. Thoroughly explore the codebase to understand existing patterns\n"
            "2. Identify similar features and architectural approaches\n"
            "3. Consider multiple approaches and their trade-offs\n"
            "4. Use AskUserQuestion if you need to clarify the approach\n"
            "5. Design a concrete implementation strategy\n"
            "6. When ready, use ExitPlanMode to present your plan for approval\n"
            "\n"
            "Remember: DO NOT write or edit any files yet. This is a read-only "
            "exploration and planning phase."
        )
        return {
            "type": "tool_result",
            "content": instructions,
            "tool_use_id": tool_use_id,
        }
