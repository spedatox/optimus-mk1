"""
tools/file_read_tool/file_read_tool.py — port of src/tools/FileReadTool/FileReadTool.ts

Read a text file with optional offset/limit, returned in cat -n format. Updates
the shared read_file_state (so Edit/Write can enforce read-before-write), with a
dedup stub for unchanged re-reads.

Porting notes (text path is full; binary formats RE-ENTRY):
  - Image (readImageWithTokenBudget), PDF (readPDF/extractPDFPages), and Jupyter
    notebook (.ipynb) reads → RE-ENTRY (need imageResizer/pdf/notebook ports).
    The map handles 'image'/'pdf'/'notebook' types when those land.
  - readFileInRange → inline read + slice; maxSizeBytes cap on full reads.
  - skills discovery / LSP / analytics → omitted.
"""
from __future__ import annotations

import os
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
from optimus.utils.file import (
    FILE_NOT_FOUND_CWD_NOTE,
    MAX_OUTPUT_SIZE,
    add_line_numbers,
    get_file_modification_time,
    suggest_path_under_cwd,
)
from optimus.utils.path import expand_path
from optimus.tools.file_read_tool.prompt import (
    DESCRIPTION,
    FILE_READ_TOOL_NAME,
    FILE_UNCHANGED_STUB,
    MAX_LINES_TO_READ,
    get_read_tool_description,
)

_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "The absolute path to the file to read"},
        "offset": {"type": "number", "description": "The line number to start reading from (1-indexed). Only for large files."},
        "limit": {"type": "number", "description": "The number of lines to read. Only for large files."},
    },
    "required": ["file_path"],
    "additionalProperties": False,
}


def _read_file_state(context: ToolUseContext) -> dict:
    if context.read_file_state is None:
        context.read_file_state = {}
    return context.read_file_state


@build_tool
class FileReadTool:
    name = FILE_READ_TOOL_NAME
    search_hint = "read file contents"
    max_result_size_chars = 100_000
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_read_tool_description()

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("file_path", "")

    def is_search_or_read_command(self, input: dict[str, Any]) -> dict[str, bool]:
        return {"isSearch": False, "isRead": True, "isList": False}

    def get_path(self, input: dict[str, Any]) -> str:
        return input.get("file_path", "")

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Reading file"

    def backfill_observable_input(self, input: dict[str, Any]) -> None:
        if isinstance(input.get("file_path"), str):
            input["file_path"] = expand_path(input["file_path"])

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        file_path = input["file_path"]
        full_file_path = expand_path(file_path)
        if full_file_path.startswith("\\\\") or full_file_path.startswith("//"):
            return ValidationResult.ok()
        try:
            stats = os.stat(full_file_path)
        except OSError as e:
            if is_enoent_error(e):
                # Allowed — call() returns a friendly not-found error.
                return ValidationResult.ok()
            raise
        if os.path.isdir(full_file_path):
            return ValidationResult.fail(
                f"Path is a directory, not a file: {file_path}. Use an ls command via Bash.",
                error_code=1,
            )
        _ = stats
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
        offset = input.get("offset", 1) or 1
        limit = input.get("limit")
        full_file_path = expand_path(file_path)
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        read_state = _read_file_state(context)

        limits = context.file_reading_limits or {}
        max_size_bytes = limits.get("maxSizeBytes", MAX_OUTPUT_SIZE)

        # Dedup: same range + unchanged mtime → stub (text reads only).
        existing = read_state.get(full_file_path)
        if existing and not existing.get("isPartialView") and existing.get("offset") is not None:
            if existing.get("offset") == offset and existing.get("limit") == limit:
                if get_file_modification_time(full_file_path) == existing.get("timestamp"):
                    return ToolResult(data={"type": "file_unchanged", "file": {"filePath": file_path}})

        # RE-ENTRY: image / PDF / notebook reads (binary formats).
        if ext == "ipynb" or ext in _IMAGE_EXTENSIONS or ext == "pdf":
            raise RuntimeError(
                f"Reading .{ext} files is not yet supported in this build "
                "(image/PDF/notebook readers are RE-ENTRY)."
            )

        try:
            with open(full_file_path, "rb") as f:
                raw = f.read()
        except OSError as e:
            if is_enoent_error(e):
                suggestion = await suggest_path_under_cwd(full_file_path)
                message = f"File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {get_cwd()}."
                if suggestion:
                    message += f" Did you mean {suggestion}?"
                raise RuntimeError(message)
            raise

        # Byte cap applies to full reads (no explicit limit).
        if limit is None and len(raw) > max_size_bytes:
            raise RuntimeError(
                f"File content ({len(raw)} bytes) exceeds maximum allowed size "
                f"({max_size_bytes} bytes). Use the offset and limit parameters to read it in chunks."
            )

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        normalized = text.replace("\r\n", "\n")
        all_lines = normalized.split("\n")
        total_lines = len(all_lines)

        line_offset = 0 if offset == 0 else offset - 1
        effective_limit = limit if limit is not None else MAX_LINES_TO_READ
        selected = all_lines[line_offset : line_offset + effective_limit]
        # Truncate very long lines to keep output bounded (cat -n parity).
        selected = [ln if len(ln) <= 2000 else ln[:2000] for ln in selected]
        content = "\n".join(selected)

        read_state[full_file_path] = {
            "content": content,
            "timestamp": get_file_modification_time(full_file_path),
            "offset": offset,
            "limit": limit,
        }

        data = {
            "type": "text",
            "file": {
                "filePath": file_path,
                "content": content,
                "numLines": len(selected),
                "startLine": offset,
                "totalLines": total_lines,
            },
        }
        return ToolResult(data=data)

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        t = data["type"]
        if t == "file_unchanged":
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": FILE_UNCHANGED_STUB}
        if t == "text":
            file = data["file"]
            if file["content"]:
                content = add_line_numbers(file["content"], file["startLine"])
            elif file["totalLines"] == 0:
                content = "<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>"
            else:
                content = (
                    f"<system-reminder>Warning: the file exists but is shorter than the provided "
                    f"offset ({file['startLine']}). The file has {file['totalLines']} lines.</system-reminder>"
                )
            return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
        # image / pdf / notebook handled when those readers land (RE-ENTRY).
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": str(data)}
