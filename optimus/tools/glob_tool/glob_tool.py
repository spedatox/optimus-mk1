"""
tools/glob_tool/glob_tool.py — port of src/tools/GlobTool/GlobTool.ts

Fast file pattern matching. Read-only, concurrency-safe.

Porting notes:
  - zod strictObject schema → input_schema dict (JSON Schema) for the API.
  - buildTool({...}) object → a @build_tool-decorated class implementing the
    snake_case Tool protocol methods.
  - UI render functions (UI.tsx) → return None (no UI layer yet).
  - checkReadPermissionForTool → allow (read-only); full read-permission gating
    is RE-ENTRY (permissions/filesystem.ts). The query loop's can_use_tool is
    still the outer gate.
  - matchWildcardPattern permission matcher → simple fnmatch-based matcher.
"""
from __future__ import annotations

import fnmatch
import os
import time
from typing import Any, Optional

from optimus.Tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.utils.cwd import get_cwd
from optimus.utils.errors import is_enoent_error
from optimus.utils.file import FILE_NOT_FOUND_CWD_NOTE, suggest_path_under_cwd
from optimus.utils.glob import glob as _glob
from optimus.utils.path import expand_path, to_relative_path
from optimus.tools.glob_tool.prompt import DESCRIPTION, GLOB_TOOL_NAME

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "The glob pattern to match files against",
        },
        "path": {
            "type": "string",
            "description": (
                "The directory to search in. If not specified, the current working "
                'directory will be used. IMPORTANT: Omit this field to use the default '
                'directory. DO NOT enter "undefined" or "null" - simply omit it for the '
                "default behavior. Must be a valid directory path if provided."
            ),
        },
    },
    "required": ["pattern"],
    "additionalProperties": False,
}


@build_tool
class GlobTool:
    name = GLOB_TOOL_NAME
    search_hint = "find files by name pattern or wildcard"
    max_result_size_chars = 100_000
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("pattern", "")

    def is_search_or_read_command(self, input: dict[str, Any]) -> dict[str, bool]:
        return {"isSearch": True, "isRead": False, "isList": False}

    def get_path(self, input: dict[str, Any]) -> str:
        path = input.get("path")
        return expand_path(path) if path else get_cwd()

    async def prepare_permission_matcher(self, input: dict[str, Any]):
        pattern = input.get("pattern", "")

        def _matcher(rule_pattern: str) -> bool:
            return fnmatch.fnmatch(pattern, rule_pattern)

        return _matcher

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Finding files"

    def extract_search_text(self, output: Any) -> str:
        return "\n".join((output or {}).get("filenames", []))

    async def validate_input(
        self, input: dict[str, Any], context: ToolUseContext
    ) -> ValidationResult:
        path = input.get("path")
        if path:
            absolute_path = expand_path(path)
            # SECURITY: skip FS ops for UNC paths (NTLM credential-leak risk).
            if absolute_path.startswith("\\\\") or absolute_path.startswith("//"):
                return ValidationResult.ok()
            try:
                stats = os.stat(absolute_path)
            except OSError as e:
                if is_enoent_error(e):
                    suggestion = await suggest_path_under_cwd(absolute_path)
                    message = (
                        f"Directory does not exist: {path}. {FILE_NOT_FOUND_CWD_NOTE} {get_cwd()}."
                    )
                    if suggestion:
                        message += f" Did you mean {suggestion}?"
                    return ValidationResult.fail(message, error_code=1)
                raise
            if not os.path.isdir(absolute_path):
                return ValidationResult.fail(f"Path is not a directory: {path}", error_code=2)
        return ValidationResult.ok()

    async def check_permissions(
        self, input: dict[str, Any], context: ToolUseContext
    ) -> PermissionResult:
        # Read-only: allow. RE-ENTRY: checkReadPermissionForTool (ignore patterns,
        # additional working directories).
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        start = time.time()
        limit = (context.glob_limits or {}).get("maxResults", 100)
        result = await _glob(
            input["pattern"],
            self.get_path(input),
            {"limit": limit, "offset": 0},
            context.abort_controller,
            context.tool_permission_context,
        )
        filenames = [to_relative_path(f) for f in result["files"]]
        output = {
            "filenames": filenames,
            "durationMs": int((time.time() - start) * 1000),
            "numFiles": len(filenames),
            "truncated": result["truncated"],
        }
        return ToolResult(data=output)

    def map_tool_result_to_tool_result_block_param(
        self, output: Any, tool_use_id: str
    ) -> dict[str, Any]:
        if len(output["filenames"]) == 0:
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": "No files found"}
        lines = list(output["filenames"])
        if output["truncated"]:
            lines.append(
                "(Results are truncated. Consider using a more specific path or pattern.)"
            )
        return {
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": "\n".join(lines),
        }
