"""
tools/file_edit_tool/file_edit_tool.py — port of src/tools/FileEditTool/FileEditTool.ts

Exact string replacement in files. Enforces read-before-edit, uniqueness of
old_string (unless replace_all), and staleness detection via read_file_state.
Empty old_string on a nonexistent/empty file means new-file creation.

Porting notes (full core; integrations RE-ENTRY):
  - LSP, skills, diagnosticTracker, fileHistory, gitDiff, teamMemSecrets,
    findActualString/preserveQuoteStyle quote-normalization → omitted/RE-ENTRY
    (plain string match used; curly-quote normalization is a later refinement).
  - line-ending + encoding preserved from the original file.
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
from optimus.utils.diff import count_lines_changed, structured_patch
from optimus.utils.errors import is_enoent_error
from optimus.utils.file import (
    FILE_NOT_FOUND_CWD_NOTE,
    get_file_modification_time,
    suggest_path_under_cwd,
    write_text_content,
)
from optimus.utils.file_read import detect_line_endings
from optimus.utils.path import expand_path
from optimus.tools.file_edit_tool.prompt import FILE_EDIT_TOOL_NAME, get_edit_tool_description
from optimus.tools.file_write_tool.file_write_tool import FILE_UNEXPECTEDLY_MODIFIED_ERROR

MAX_EDIT_FILE_SIZE = 10 * 1024 * 1024  # mirrors MAX_EDIT_FILE_SIZE (10MB)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "The absolute path to the file to modify"},
        "old_string": {"type": "string", "description": "The text to replace"},
        "new_string": {"type": "string", "description": "The text to replace it with (must be different from old_string)"},
        "replace_all": {"type": "boolean", "description": "Replace all occurrences of old_string (default false)", "default": False},
    },
    "required": ["file_path", "old_string", "new_string"],
    "additionalProperties": False,
}


def _read_file_state(context: ToolUseContext) -> dict:
    if context.read_file_state is None:
        context.read_file_state = {}
    return context.read_file_state


def _read_for_edit(path: str) -> dict[str, Any]:
    """Return {'content', 'fileExists', 'encoding', 'lineEndings'}."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        if is_enoent_error(e):
            return {"content": "", "fileExists": False, "encoding": "utf-8", "lineEndings": "LF"}
        raise
    if len(raw) >= 2 and raw[0] == 0xFF and raw[1] == 0xFE:
        encoding = "utf-16-le"
    else:
        encoding = "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        encoding = "latin-1"
    line_endings = detect_line_endings(text)
    return {
        "content": text.replace("\r\n", "\n"),
        "fileExists": True,
        "encoding": encoding,
        "lineEndings": line_endings,
    }


@build_tool
class FileEditTool:
    name = FILE_EDIT_TOOL_NAME
    search_hint = "edit files with exact string replacement"
    max_result_size_chars = 100_000
    strict = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return "Performs exact string replacement in a file."

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_edit_tool_description()

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return f"{input.get('file_path')}: {input.get('old_string')}"

    def get_path(self, input: dict[str, Any]) -> str:
        return input["file_path"]

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return False

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Editing file"

    def backfill_observable_input(self, input: dict[str, Any]) -> None:
        if isinstance(input.get("file_path"), str):
            input["file_path"] = expand_path(input["file_path"])

    async def prepare_permission_matcher(self, input: dict[str, Any]):
        import fnmatch

        file_path = input.get("file_path", "")
        return lambda pattern: fnmatch.fnmatch(file_path, pattern)

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        file_path = input["file_path"]
        old_string = input["old_string"]
        new_string = input["new_string"]
        replace_all = input.get("replace_all", False)
        full_file_path = expand_path(file_path)

        if old_string == new_string:
            return ValidationResult.fail(
                "No changes to make: old_string and new_string are exactly the same.", error_code=1
            )

        if full_file_path.startswith("\\\\") or full_file_path.startswith("//"):
            return ValidationResult.ok()

        try:
            size = os.stat(full_file_path).st_size
            if size > MAX_EDIT_FILE_SIZE:
                return ValidationResult.fail(
                    f"File is too large to edit ({size} bytes). "
                    f"Maximum editable file size is {MAX_EDIT_FILE_SIZE} bytes.",
                    error_code=10,
                )
        except OSError as e:
            if not is_enoent_error(e):
                raise

        read = _read_for_edit(full_file_path)
        file_content = read["content"] if read["fileExists"] else None

        if file_content is None:
            if old_string == "":
                return ValidationResult.ok()  # new file creation
            suggestion = await suggest_path_under_cwd(full_file_path)
            message = f"File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {get_cwd()}."
            if suggestion:
                message += f" Did you mean {suggestion}?"
            return ValidationResult.fail(message, error_code=4)

        if old_string == "":
            if file_content.strip() != "":
                return ValidationResult.fail("Cannot create new file - file already exists.", error_code=3)
            return ValidationResult.ok()

        if full_file_path.endswith(".ipynb"):
            return ValidationResult.fail(
                "File is a Jupyter Notebook. Use the NotebookEdit tool to edit this file.", error_code=5
            )

        read_state = _read_file_state(context)
        read_timestamp = read_state.get(full_file_path)
        if not read_timestamp or read_timestamp.get("isPartialView"):
            return ValidationResult.fail(
                "File has not been read yet. Read it first before writing to it.", error_code=6
            )

        last_write_time = get_file_modification_time(full_file_path)
        if last_write_time > read_timestamp["timestamp"]:
            is_full_read = (
                read_timestamp.get("offset") is None and read_timestamp.get("limit") is None
            )
            if not (is_full_read and file_content == read_timestamp.get("content")):
                return ValidationResult.fail(
                    "File has been modified since read, either by the user or by a linter. "
                    "Read it again before attempting to write it.",
                    error_code=7,
                )

        if old_string not in file_content:
            return ValidationResult.fail(
                f"String to replace not found in file.\nString: {old_string}", error_code=8
            )

        matches = file_content.count(old_string)
        if matches > 1 and not replace_all:
            return ValidationResult.fail(
                f"Found {matches} matches of the string to replace, but replace_all is false. "
                "To replace all occurrences, set replace_all to true. To replace only one "
                "occurrence, provide more context to uniquely identify the instance.",
                error_code=9,
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
        old_string = input["old_string"]
        new_string = input["new_string"]
        replace_all = input.get("replace_all", False)
        absolute_file_path = expand_path(file_path)
        read_state = _read_file_state(context)

        os.makedirs(os.path.dirname(absolute_file_path), exist_ok=True)

        read = _read_for_edit(absolute_file_path)
        original_file_contents = read["content"]
        file_exists = read["fileExists"]
        encoding = read["encoding"]
        endings = read["lineEndings"]

        if file_exists:
            last_write_time = get_file_modification_time(absolute_file_path)
            last_read = read_state.get(absolute_file_path)
            if not last_read or last_write_time > last_read["timestamp"]:
                is_full_read = (
                    last_read
                    and last_read.get("offset") is None
                    and last_read.get("limit") is None
                )
                content_unchanged = is_full_read and original_file_contents == last_read.get("content")
                if not content_unchanged:
                    raise RuntimeError(FILE_UNEXPECTEDLY_MODIFIED_ERROR)

        # Apply the replacement.
        if old_string == "":
            updated_file = new_string  # new-file / empty-file creation
        elif replace_all:
            updated_file = original_file_contents.replace(old_string, new_string)
        else:
            updated_file = original_file_contents.replace(old_string, new_string, 1)

        write_text_content(absolute_file_path, updated_file, encoding, endings)

        patch = structured_patch(original_file_contents, updated_file, file_path)

        read_state[absolute_file_path] = {
            "content": updated_file,
            "timestamp": get_file_modification_time(absolute_file_path),
            "offset": None,
            "limit": None,
        }
        count_lines_changed(patch)

        return ToolResult(
            data={
                "filePath": file_path,
                "oldString": old_string,
                "newString": new_string,
                "originalFile": original_file_contents,
                "structuredPatch": patch,
                "userModified": bool(context.user_modified),
                "replaceAll": replace_all,
            }
        )

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        file_path = data["filePath"]
        modified_note = (
            ".  The user modified your proposed changes before accepting them. "
            if data.get("userModified")
            else ""
        )
        if data.get("replaceAll"):
            content = f"The file {file_path} has been updated{modified_note}. All occurrences were successfully replaced."
        else:
            content = f"The file {file_path} has been updated successfully{modified_note}."
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
