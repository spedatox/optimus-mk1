"""tools/agent_tool/agent_tool.py — port of src/tools/AgentTool (restored from
commit f696afe, upgraded to the current Tool protocol and wired to the real
query loop).

Spawns a sub-agent: a fresh query() run with its own ToolUseContext (agent_id
set), a per-agent-type system prompt, and a tool pool filtered by agent type
(Explore/Plan get read-only tools). The sub-agent's final text is returned as
the tool result.

Porting notes:
  - Parallel agents / background agents / worktree isolation / resumption via
    SendMessage → RE-ENTRY. One synchronous sub-query per call.
  - The parent's can_use_tool gate is passed through, so sub-agent tool calls
    obey the same permission surface as the parent's.
  - Sub-agent nesting is blocked (an agent context cannot spawn agents),
    matching the source.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ToolUseContextOptions,
    ValidationResult,
    build_tool,
)
from optimus.tools.agent_tool.prompt import (
    AGENT_SYSTEM_PROMPTS,
    AGENT_TOOL_NAME,
    DEFAULT_AGENT_SYSTEM_PROMPT,
    DESCRIPTION,
    LEGACY_AGENT_TOOL_NAME,
    PROMPT,
)

_READ_ONLY_AGENT_TYPES = {"Explore", "Plan"}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the task",
        },
        "prompt": {
            "type": "string",
            "description": "The task for the agent to perform",
        },
        "subagent_type": {
            "type": "string",
            "description": (
                "The type of specialized agent to use: 'general-purpose' "
                "(default), 'Explore', or 'Plan'."
            ),
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}


def _tools_for_agent(subagent_type: str, parent_tools: list) -> list:
    """Filter the tool pool for the sub-agent: no nested Agent tool, and
    read-only tools only for Explore/Plan."""
    tools = [t for t in parent_tools if t.name not in (AGENT_TOOL_NAME, LEGACY_AGENT_TOOL_NAME)]
    if subagent_type in _READ_ONLY_AGENT_TYPES:
        tools = [t for t in tools if t.is_read_only({})]
    return tools


@build_tool
class AgentTool:
    name = AGENT_TOOL_NAME
    aliases = [LEGACY_AGENT_TOOL_NAME]
    search_hint = "spawn a sub-agent for complex multi-step or fan-out tasks"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 200_000
    strict = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True  # agents may run in parallel

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return (input or {}).get("subagent_type") in _READ_ONLY_AGENT_TYPES

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        if input and input.get("description"):
            return input["description"]
        return "Running agent"

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("description", "")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("prompt", "").strip():
            return ValidationResult.fail("prompt must not be empty", error_code=1)
        if context.agent_id:
            return ValidationResult.fail(
                "Agent tool cannot be used from within an agent context", error_code=2
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
        from optimus.api import call_model
        from optimus.query import QueryParams, production_deps, query

        prompt: str = input["prompt"]
        subagent_type: str = input.get("subagent_type") or "general-purpose"
        system = AGENT_SYSTEM_PROMPTS.get(subagent_type, DEFAULT_AGENT_SYSTEM_PROMPT)

        parent_tools = list(context.options.tools or [])
        agent_tools = _tools_for_agent(subagent_type, parent_tools)

        sub_ctx = ToolUseContext(
            options=ToolUseContextOptions(
                main_loop_model=context.options.main_loop_model,
                tools=agent_tools,
                mcp_clients=context.options.mcp_clients,
                verbose=context.options.verbose,
                debug=context.options.debug,
                is_non_interactive_session=True,
                query_source="agent",
            ),
            abort_controller=context.abort_controller,  # parent abort cancels the sub-agent
            agent_id=str(_uuid.uuid4()),
            agent_type=subagent_type,
            tool_permission_context=context.tool_permission_context,
        )

        params = QueryParams(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=[system],
            user_context=None,
            system_context=None,
            can_use_tool=can_use_tool if can_use_tool is not None else (lambda *_: True),
            tool_use_context=sub_ctx,
            query_source="agent",
            deps=production_deps(call_model=call_model),
        )

        text_parts: list[str] = []
        tool_use_count = 0
        async for event in query(params):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "assistant":
                # Keep only the latest assistant text — the final message is
                # the agent's report (intermediate turns end in tool calls).
                blocks = event.get("message", {}).get("content", [])
                turn_text = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                tool_use_count += sum(1 for b in blocks if b.get("type") == "tool_use")
                if turn_text:
                    text_parts = turn_text
        result_text = "\n".join(text_parts).strip()
        return ToolResult(
            data={
                "result": result_text or "(agent completed with no output)",
                "agentType": subagent_type,
                "toolUseCount": tool_use_count,
            }
        )

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        content = data["result"] if isinstance(data, dict) else str(data)
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
