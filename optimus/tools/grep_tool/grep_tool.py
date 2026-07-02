"""
tools/grep_tool/grep_tool.py — port of src/tools/GrepTool/GrepTool.ts

Regex content search over files (ripgrep-backed). Read-only, concurrency-safe.
Three output modes: files_with_matches (default), content, count.

Porting notes: see utils/ripgrep.py for the rg/Python-fallback details. UI render
fns → None. checkReadPermissionForTool → allow (RE-ENTRY for full read gating).
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
from optimus.utils.path import expand_path, to_relative_path
from optimus.utils.ripgrep import rip_grep
from optimus.tools.grep_tool.prompt import GREP_TOOL_NAME, get_description

_VCS_DIRECTORIES_TO_EXCLUDE = [".git", ".svn", ".hg", ".bzr", ".jj", ".sl"]
DEFAULT_HEAD_LIMIT = 250


def _plural(n: int, word: str) -> str:
    return word if n == 1 else word + "s"


def _apply_head_limit(items: list, limit: Optional[int], offset: int = 0) -> dict[str, Any]:
    if limit == 0:
        return {"items": items[offset:], "appliedLimit": None}
    effective_limit = limit if limit is not None else DEFAULT_HEAD_LIMIT
    sliced = items[offset : offset + effective_limit]
    was_truncated = len(items) - offset > effective_limit
    return {"items": sliced, "appliedLimit": effective_limit if was_truncated else None}


def _format_limit_info(applied_limit: Optional[int], applied_offset: Optional[int]) -> str:
    parts = []
    if applied_limit is not None:
        parts.append(f"limit: {applied_limit}")
    if applied_offset:
        parts.append(f"offset: {applied_offset}")
    return ", ".join(parts)


_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "The regular expression pattern to search for in file contents"},
        "path": {"type": "string", "description": "File or directory to search in (rg PATH). Defaults to current working directory."},
        "glob": {"type": "string", "description": 'Glob pattern to filter files (e.g. "*.js", "*.{ts,tsx}") - maps to rg --glob'},
        "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"], "description": 'Output mode. Defaults to "files_with_matches".'},
        "-B": {"type": "number", "description": "Lines to show before each match (content mode)."},
        "-A": {"type": "number", "description": "Lines to show after each match (content mode)."},
        "-C": {"type": "number", "description": "Lines to show before and after each match (content mode)."},
        "context": {"type": "number", "description": "Alias for -C."},
        "-n": {"type": "boolean", "description": "Show line numbers (content mode). Defaults true."},
        "-i": {"type": "boolean", "description": "Case insensitive search."},
        "type": {"type": "string", "description": "File type to search (js, py, rust, go, ...)."},
        "head_limit": {"type": "number", "description": "Limit output to first N entries. Default 250; 0 = unlimited."},
        "offset": {"type": "number", "description": "Skip first N entries before head_limit. Default 0."},
        "multiline": {"type": "boolean", "description": "Enable multiline mode (. matches newlines)."},
    },
    "required": ["pattern"],
    "additionalProperties": False,
}


@build_tool
class GrepTool:
    name = GREP_TOOL_NAME
    search_hint = "search file contents with regex (ripgrep)"
    max_result_size_chars = 20_000
    strict = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return get_description()

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_description()

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return "Search"

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return f"{input['pattern']} in {input['path']}" if input.get("path") else input.get("pattern", "")

    def is_search_or_read_command(self, input: dict[str, Any]) -> dict[str, bool]:
        return {"isSearch": True, "isRead": False, "isList": False}

    def get_path(self, input: dict[str, Any]) -> str:
        return input.get("path") or get_cwd()

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Searching"

    def extract_search_text(self, output: Any) -> str:
        output = output or {}
        if output.get("mode") == "content" and output.get("content"):
            return output["content"]
        return "\n".join(output.get("filenames", []))

    async def prepare_permission_matcher(self, input: dict[str, Any]):
        pattern = input.get("pattern", "")
        return lambda rule: fnmatch.fnmatch(pattern, rule)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        path = input.get("path")
        if path:
            absolute_path = expand_path(path)
            if absolute_path.startswith("\\\\") or absolute_path.startswith("//"):
                return ValidationResult.ok()
            try:
                os.stat(absolute_path)
            except OSError as e:
                if is_enoent_error(e):
                    suggestion = await suggest_path_under_cwd(absolute_path)
                    message = f"Path does not exist: {path}. {FILE_NOT_FOUND_CWD_NOTE} {get_cwd()}."
                    if suggestion:
                        message += f" Did you mean {suggestion}?"
                    return ValidationResult.fail(message, error_code=1)
                raise
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
        pattern = input["pattern"]
        path = input.get("path")
        glob = input.get("glob")
        type_ = input.get("type")
        output_mode = input.get("output_mode", "files_with_matches")
        context_before = input.get("-B")
        context_after = input.get("-A")
        context_c = input.get("-C")
        context_val = input.get("context")
        show_line_numbers = input.get("-n", True)
        case_insensitive = input.get("-i", False)
        head_limit = input.get("head_limit")
        offset = input.get("offset", 0)
        multiline = input.get("multiline", False)

        absolute_path = expand_path(path) if path else get_cwd()
        args = ["--hidden"]
        for d in _VCS_DIRECTORIES_TO_EXCLUDE:
            args += ["--glob", f"!{d}"]
        args += ["--max-columns", "500"]
        if multiline:
            args += ["-U", "--multiline-dotall"]
        if case_insensitive:
            args.append("-i")
        if output_mode == "files_with_matches":
            args.append("-l")
        elif output_mode == "count":
            args.append("-c")
        if show_line_numbers and output_mode == "content":
            args.append("-n")
        if output_mode == "content":
            if context_val is not None:
                args += ["-C", str(context_val)]
            elif context_c is not None:
                args += ["-C", str(context_c)]
            else:
                if context_before is not None:
                    args += ["-B", str(context_before)]
                if context_after is not None:
                    args += ["-A", str(context_after)]
        if pattern.startswith("-"):
            args += ["-e", pattern]
        else:
            args.append(pattern)
        if type_:
            args += ["--type", type_]
        if glob:
            glob_patterns = []
            for raw in glob.split():
                if "{" in raw and "}" in raw:
                    glob_patterns.append(raw)
                else:
                    glob_patterns += [g for g in raw.split(",") if g]
            for g in glob_patterns:
                args += ["--glob", g]

        results = await rip_grep(args, absolute_path, context.abort_controller)

        if output_mode == "content":
            limited = _apply_head_limit(results, head_limit, offset)
            final_lines = []
            for line in limited["items"]:
                colon_index = line.find(":")
                if colon_index > 0:
                    final_lines.append(to_relative_path(line[:colon_index]) + line[colon_index:])
                else:
                    final_lines.append(line)
            output = {
                "mode": "content",
                "numFiles": 0,
                "filenames": [],
                "content": "\n".join(final_lines),
                "numLines": len(final_lines),
            }
            if limited["appliedLimit"] is not None:
                output["appliedLimit"] = limited["appliedLimit"]
            if offset > 0:
                output["appliedOffset"] = offset
            return ToolResult(data=output)

        if output_mode == "count":
            limited = _apply_head_limit(results, head_limit, offset)
            final_count_lines = []
            for line in limited["items"]:
                colon_index = line.rfind(":")
                if colon_index > 0:
                    final_count_lines.append(to_relative_path(line[:colon_index]) + line[colon_index:])
                else:
                    final_count_lines.append(line)
            total_matches = 0
            file_count = 0
            for line in final_count_lines:
                colon_index = line.rfind(":")
                if colon_index > 0:
                    try:
                        total_matches += int(line[colon_index + 1 :])
                        file_count += 1
                    except ValueError:
                        pass
            output = {
                "mode": "count",
                "numFiles": file_count,
                "filenames": [],
                "content": "\n".join(final_count_lines),
                "numMatches": total_matches,
            }
            if limited["appliedLimit"] is not None:
                output["appliedLimit"] = limited["appliedLimit"]
            if offset > 0:
                output["appliedOffset"] = offset
            return ToolResult(data=output)

        # files_with_matches (default) — sort by mtime desc, filename tiebreak.
        def _mtime(p: str) -> float:
            try:
                return os.stat(p).st_mtime
            except OSError:
                return 0.0

        sorted_matches = sorted(results, key=lambda p: (-_mtime(p), p))
        limited = _apply_head_limit(sorted_matches, head_limit, offset)
        relative_matches = [to_relative_path(m) for m in limited["items"]]
        output = {
            "mode": "files_with_matches",
            "filenames": relative_matches,
            "numFiles": len(relative_matches),
        }
        if limited["appliedLimit"] is not None:
            output["appliedLimit"] = limited["appliedLimit"]
        if offset > 0:
            output["appliedOffset"] = offset
        return ToolResult(data=output)

    def map_tool_result_to_tool_result_block_param(self, output: Any, tool_use_id: str) -> dict[str, Any]:
        mode = output.get("mode", "files_with_matches")
        applied_limit = output.get("appliedLimit")
        applied_offset = output.get("appliedOffset")
        limit_info = _format_limit_info(applied_limit, applied_offset)

        if mode == "content":
            content = output.get("content") or "No matches found"
            final = f"{content}\n\n[Showing results with pagination = {limit_info}]" if limit_info else content
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": final}

        if mode == "count":
            raw = output.get("content") or "No matches found"
            matches = output.get("numMatches", 0)
            files = output.get("numFiles", 0)
            summary = (
                f"\n\nFound {matches} total {_plural(matches, 'occurrence')} across "
                f"{files} {_plural(files, 'file')}."
                + (f" with pagination = {limit_info}" if limit_info else "")
            )
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": raw + summary}

        num_files = output.get("numFiles", 0)
        if num_files == 0:
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": "No files found"}
        result = (
            f"Found {num_files} {_plural(num_files, 'file')}"
            + (f" {limit_info}" if limit_info else "")
            + "\n"
            + "\n".join(output["filenames"])
        )
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": result}
