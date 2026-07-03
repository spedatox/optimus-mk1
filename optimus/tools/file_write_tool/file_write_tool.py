"""
tools/file_write_tool/file_write_tool.py — port of src/tools/FileWriteTool/FileWriteTool.ts

Create or overwrite a file. Enforces read-before-overwrite and staleness checks
via the shared read_file_state, writes with LF endings, and returns a structured
patch for updates.

Porting notes (peripheral integrations are RE-ENTRY, not core to writing bytes):
  - LSP didChange/didSave, skill discovery/activation, diagnosticTracker,
    fileHistory backup, gitDiff, teamMemSecret guard, analytics → omitted/RE-ENTRY.
  - readFileState comes from context.read_file_state (a ReadFileState dict).
  - FILE_UNEXPECTEDLY_MODIFIED_ERROR preserved.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.utils.cwd import get_cwd
from optimus.utils.diff import count_lines_changed, get_patch_for_display
from optimus.utils.errors import is_enoent_error
from optimus.utils.file import get_file_modification_time, write_text_content
from optimus.utils.file_read import read_file_sync_with_metadata
from optimus.utils.path import expand_path
from optimus.tools.file_write_tool.prompt import FILE_WRITE_TOOL_NAME, get_write_tool_description

FILE_UNEXPECTEDLY_MODIFIED_ERROR = (
    "File has been unexpectedly modified since read. Read it again before writing."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "The absolute path to the file to write (must be absolute, not relative)"},
        "content": {"type": "string", "description": "The content to write to the file"},
    },
    "required": ["file_path", "content"],
    "additionalProperties": False,
}


def _read_file_state(context: ToolUseContext) -> dict:
    if context.read_file_state is None:
        context.read_file_state = {}
    return context.read_file_state


@build_tool
class FileWriteTool:
    name = FILE_WRITE_TOOL_NAME
    search_hint = "create or overwrite files"
    max_result_size_chars = 100_000
    strict = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return "Write a file to the local filesystem."

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_write_tool_description()

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return f"{input.get('file_path')}: {input.get('content')}"

    def get_path(self, input: dict[str, Any]) -> str:
        return input["file_path"]

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return False

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Writing file"

    def backfill_observable_input(self, input: dict[str, Any]) -> None:
        # hooks document file_path as absolute; expand so allowlists can't be
        # bypassed via ~ or relative paths.
        if isinstance(input.get("file_path"), str):
            input["file_path"] = expand_path(input["file_path"])

    async def prepare_permission_matcher(self, input: dict[str, Any]):
        import fnmatch

        file_path = input.get("file_path", "")
        return lambda pattern: fnmatch.fnmatch(file_path, pattern)

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        # RE-ENTRY: checkWritePermissionForTool (deny/ask rules). Allow here;
        # the query loop's can_use_tool is the outer gate.
        return PermissionResult(behavior="allow", updated_input=input)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        full_file_path = expand_path(input["file_path"])

        if full_file_path.startswith("\\\\") or full_file_path.startswith("//"):
            return ValidationResult.ok()

        try:
            file_stat = os.stat(full_file_path)
        except OSError as e:
            if is_enoent_error(e):
                return ValidationResult.ok()  # new file
            raise

        read_state = _read_file_state(context)
        read_timestamp = read_state.get(full_file_path)
        if not read_timestamp or read_timestamp.get("isPartialView"):
            return ValidationResult.fail(
                "File has not been read yet. Read it first before writing to it.", error_code=2
            )

        last_write_time = int(file_stat.st_mtime * 1000)
        if last_write_time > read_timestamp["timestamp"]:
            return ValidationResult.fail(
                "File has been modified since read, either by the user or by a linter. "
                "Read it again before attempting to write it.",
                error_code=3,
            )
        return ValidationResult.ok()

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        file_path = input["file_path"]
        content = input["content"]
        full_file_path = expand_path(file_path)
        directory = os.path.dirname(full_file_path)
        read_state = _read_file_state(context)

        os.makedirs(directory, exist_ok=True)

        # Load current state and confirm no changes since last read (atomic section).
        try:
            meta = read_file_sync_with_metadata(full_file_path)
        except OSError as e:
            if is_enoent_error(e):
                meta = None
            else:
                raise

        if meta is not None:
            last_write_time = get_file_modification_time(full_file_path)
            last_read = read_state.get(full_file_path)
            if not last_read or last_write_time > last_read["timestamp"]:
                is_full_read = (
                    last_read
                    and last_read.get("offset") is None
                    and last_read.get("limit") is None
                )
                if not is_full_read or meta["content"] != last_read.get("content"):
                    raise RuntimeError(FILE_UNEXPECTEDLY_MODIFIED_ERROR)

        enc = meta["encoding"] if meta else "utf-8"
        old_content = meta["content"] if meta else None

        write_text_content(full_file_path, content, enc, "LF")

        # Update read timestamp to invalidate stale writes.
        read_state[full_file_path] = {
            "content": content,
            "timestamp": get_file_modification_time(full_file_path),
            "offset": None,
            "limit": None,
        }

        if old_content:
            patch = get_patch_for_display(
                file_path=file_path,
                file_contents=old_content,
                edits=[{"old_string": old_content, "new_string": content, "replace_all": False}],
            )
            count_lines_changed(patch)
            return ToolResult(
                data={
                    "type": "update",
                    "filePath": file_path,
                    "content": content,
                    "structuredPatch": patch,
                    "originalFile": old_content,
                }
            )

        count_lines_changed([], content)
        return ToolResult(
            data={
                "type": "create",
                "filePath": file_path,
                "content": content,
                "structuredPatch": [],
                "originalFile": None,
            }
        )

    def map_tool_result_to_tool_result_block_param(self, output: Any, tool_use_id: str) -> dict[str, Any]:
        if output["type"] == "create":
            content = f"File created successfully at: {output['filePath']}"
        else:
            content = f"The file {output['filePath']} has been updated successfully."
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
