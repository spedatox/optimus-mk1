"""tools/enter_worktree_tool/enter_worktree_tool.py — port of
src/tools/EnterWorktreeTool (restored from commit f696afe, upgraded to the
current Tool protocol; cwd switch goes through bootstrap state)."""
from __future__ import annotations

import asyncio
import re
import secrets
from pathlib import Path
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.bootstrap.state import set_cwd_state
from optimus.tools.enter_worktree_tool.prompt import (
    DESCRIPTION,
    ENTER_WORKTREE_TOOL_NAME,
    PROMPT,
)
from optimus.utils.cwd import get_cwd
from optimus.utils.git import find_git_root

_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "Optional name for the worktree. Each '/'-separated segment may "
                "contain only letters, digits, dots, underscores, and dashes; max "
                "64 chars total. A random name is generated if not provided."
            ),
        },
    },
    "required": [],
    "additionalProperties": False,
}


def _validate_slug(name: str) -> Optional[str]:
    """Return an error message if the slug is invalid, else None."""
    if len(name) > 64:
        return "Worktree name must be at most 64 characters."
    for part in name.split("/"):
        if not part:
            return "Slug segments must not be empty."
        if not _SLUG_RE.match(part):
            return (
                f"Invalid slug segment '{part}': only letters, digits, dots, "
                "underscores, dashes allowed."
            )
    return None


@build_tool
class EnterWorktreeTool:
    name = ENTER_WORKTREE_TOOL_NAME
    search_hint = "work in an isolated git worktree"
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
        return False  # creates a branch + directory

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        name = input.get("name")
        if name:
            err = _validate_slug(name)
            if err:
                return ValidationResult.fail(err, error_code=1)
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
        name = input.get("name") or f"optimus-{secrets.token_hex(4)}"

        git_root = find_git_root(get_cwd())
        if git_root is None:
            return ToolResult(data={"error": "Not inside a git repository."})

        worktree_path = str(Path(git_root).parent / ".worktrees" / name)
        branch_name = f"optimus/{name}"

        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch_name, worktree_path,
            cwd=git_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return ToolResult(data={
                "error": f"Error creating worktree: {stderr.decode('utf-8', errors='replace')}"
            })

        set_cwd_state(worktree_path)
        return ToolResult(data={
            "worktreePath": worktree_path,
            "worktreeBranch": branch_name,
            "message": f"Switched to worktree '{name}' at {worktree_path}.",
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result", "content": data["message"], "tool_use_id": tool_use_id}
