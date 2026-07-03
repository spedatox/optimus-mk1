"""tools/exit_worktree_tool/exit_worktree_tool.py — port of
src/tools/ExitWorktreeTool (restored from commit f696afe, upgraded to the
current Tool protocol; cwd switch goes through bootstrap state)."""
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
from optimus.bootstrap.state import set_cwd_state
from optimus.tools.exit_worktree_tool.prompt import (
    DESCRIPTION,
    EXIT_WORKTREE_TOOL_NAME,
    PROMPT,
)
from optimus.utils.cwd import get_cwd
from optimus.utils.git import find_canonical_git_root

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["keep", "remove"],
            "description": '"keep" leaves the worktree on disk; "remove" deletes it',
        },
        "discard_changes": {
            "type": "boolean",
            "description": (
                "Required true when action is 'remove' and the worktree has "
                "uncommitted files or unmerged commits"
            ),
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


@build_tool
class ExitWorktreeTool:
    name = EXIT_WORKTREE_TOOL_NAME
    search_hint = "leave the current git worktree"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 20_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return (input or {}).get("action") == "keep"

    def is_destructive(self, input: dict[str, Any]) -> bool:
        return bool((input or {}).get("discard_changes"))

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if input.get("action") not in ("keep", "remove"):
            return ValidationResult.fail("action must be 'keep' or 'remove'", error_code=1)
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        if input.get("action") == "remove" and input.get("discard_changes"):
            # Discarding work is destructive — always confirm.
            return PermissionResult(
                behavior="ask", updated_input=input,
                message="Remove the worktree and discard its uncommitted changes?",
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
        action: str = input["action"]
        discard: bool = bool(input.get("discard_changes", False))

        current_wt = get_cwd()
        canonical_root = find_canonical_git_root(current_wt)
        if canonical_root is None:
            return ToolResult(data={"error": "Not inside a git repository."})

        if action == "remove":
            if not discard:
                proc = await asyncio.create_subprocess_exec(
                    "git", "status", "--porcelain",
                    cwd=current_wt,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if stdout.strip():
                    return ToolResult(data={"error": (
                        "Worktree has uncommitted changes. "
                        "Set discard_changes=true to force removal."
                    )})

            argv = ["git", "worktree", "remove"]
            if discard:
                argv.append("--force")
            argv.append(current_wt)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=canonical_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return ToolResult(data={
                    "error": f"Error removing worktree: {stderr.decode('utf-8', errors='replace')}"
                })

        set_cwd_state(canonical_root)
        return ToolResult(data={
            "action": action,
            "originalCwd": canonical_root,
            "message": f"Exited worktree ({action}). CWD is now {canonical_root}.",
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result", "content": data["message"], "tool_use_id": tool_use_id}
