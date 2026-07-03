"""
tools/notebook_edit_tool/notebook_edit_tool.py — port of
src/tools/NotebookEditTool/NotebookEditTool.ts

Replace / insert / delete a single cell in a Jupyter (.ipynb) notebook.
Enforces read-before-edit and staleness detection via read_file_state, exactly
like FileEditTool/FileWriteTool. Cell addressing matches the TS source: first a
real cell-id lookup, falling back to a numeric "cell-N" index.

Porting notes (full core; integrations RE-ENTRY):
  - fileHistory (fileHistoryEnabled / fileHistoryTrackEdit) → omitted, matches
    FileEditTool/FileWriteTool. The hook point is marked below.
  - UI.tsx render fns (React) → return None (no UI layer); getToolUseSummary is
    pure logic and kept, since getActivityDescription builds on it.
  - checkWritePermissionForTool → allow, deferring to the query loop's
    can_use_tool outer gate (same convention as the other file tools).
  - feature('TRANSCRIPT_CLASSIFIER') → False, so to_auto_classifier_input → ''.
"""
from __future__ import annotations

import os
import random
import string
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.utils.errors import is_enoent_error
from optimus.utils.file import get_display_path, get_file_modification_time, write_text_content
from optimus.utils.file_read import read_file_sync_with_metadata
from optimus.utils.json import json_parse, json_stringify, safe_parse_json
from optimus.utils.notebook import parse_cell_id
from optimus.utils.path import expand_path
from optimus.tools.notebook_edit_tool.constants import NOTEBOOK_EDIT_TOOL_NAME
from optimus.tools.notebook_edit_tool.prompt import DESCRIPTION, PROMPT

# Jupyter notebooks are conventionally pretty-printed with a 1-space indent.
_IPYNB_INDENT = 1

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "notebook_path": {
            "type": "string",
            "description": (
                "The absolute path to the Jupyter notebook file to edit "
                "(must be absolute, not relative)"
            ),
        },
        "cell_id": {
            "type": "string",
            "description": (
                "The ID of the cell to edit. When inserting a new cell, the new "
                "cell will be inserted after the cell with this ID, or at the "
                "beginning if not specified."
            ),
        },
        "new_source": {"type": "string", "description": "The new source for the cell"},
        "cell_type": {
            "type": "string",
            "enum": ["code", "markdown"],
            "description": (
                "The type of the cell (code or markdown). If not specified, it "
                "defaults to the current cell type. If using edit_mode=insert, "
                "this is required."
            ),
        },
        "edit_mode": {
            "type": "string",
            "enum": ["replace", "insert", "delete"],
            "description": "The type of edit to make (replace, insert, delete). Defaults to replace.",
        },
    },
    "required": ["notebook_path", "new_source"],
    "additionalProperties": False,
}


def _read_file_state(context: ToolUseContext) -> dict:
    if context.read_file_state is None:
        context.read_file_state = {}
    return context.read_file_state


def _find_cell_index(cells: list[dict[str, Any]], cell_id: str) -> int:
    """First index whose cell.id === cell_id, or -1 (mirrors Array.findIndex)."""
    for i, cell in enumerate(cells):
        if cell.get("id") == cell_id:
            return i
    return -1


def _new_random_cell_id() -> str:
    """Mirrors Math.random().toString(36).substring(2, 15) — a 13-char base36 id."""
    alphabet = string.ascii_lowercase + string.digits  # base-36 alphabet
    return "".join(random.choices(alphabet, k=13))


@build_tool
class NotebookEditTool:
    name = NOTEBOOK_EDIT_TOOL_NAME
    search_hint = "edit Jupyter notebook cells (.ipynb)"
    max_result_size_chars = 100_000
    strict = True
    should_defer = True
    input_schema = _INPUT_SCHEMA

    async def description(
        self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None
    ) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return "Edit Notebook"

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        # feature('TRANSCRIPT_CLASSIFIER') is False → classifier input skipped.
        return ""

    def get_path(self, input: dict[str, Any]) -> str:
        return input["notebook_path"]

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, input: Optional[dict[str, Any]]) -> Optional[str]:
        if not input or not input.get("notebook_path"):
            return None
        return get_display_path(input["notebook_path"])

    def get_activity_description(self, input: Optional[dict[str, Any]]) -> Optional[str]:
        summary = self.get_tool_use_summary(input)
        return f"Editing notebook {summary}" if summary else "Editing notebook"

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        # checkWritePermissionForTool → allow; the query loop's can_use_tool is
        # the outer permission gate (same convention as FileEditTool/FileWriteTool).
        return PermissionResult(behavior="allow", updated_input=input)

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        error = data.get("error")
        if error:
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": error,
                "is_error": True,
            }
        edit_mode = data.get("edit_mode", "replace")
        cell_id = data.get("cell_id")
        new_source = data.get("new_source", "")
        if edit_mode == "replace":
            content = f"Updated cell {cell_id} with {new_source}"
        elif edit_mode == "insert":
            content = f"Inserted cell {cell_id} with {new_source}"
        elif edit_mode == "delete":
            content = f"Deleted cell {cell_id}"
        else:
            content = "Unknown edit mode"
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        notebook_path = input["notebook_path"]
        cell_type = input.get("cell_type")
        cell_id = input.get("cell_id")
        edit_mode = input.get("edit_mode", "replace")

        full_path = expand_path(notebook_path)

        # SECURITY: Skip filesystem operations for UNC paths to prevent NTLM credential leaks.
        if full_path.startswith("\\\\") or full_path.startswith("//"):
            return ValidationResult.ok()

        if os.path.splitext(full_path)[1] != ".ipynb":
            return ValidationResult.fail(
                "File must be a Jupyter notebook (.ipynb file). For editing other file types, use the FileEdit tool.",
                error_code=2,
            )

        if edit_mode not in ("replace", "insert", "delete"):
            return ValidationResult.fail("Edit mode must be replace, insert, or delete.", error_code=4)

        if edit_mode == "insert" and not cell_type:
            return ValidationResult.fail(
                "Cell type is required when using edit_mode=insert.", error_code=5
            )

        # Require Read-before-Edit (matches FileEditTool/FileWriteTool). Without
        # this, the model could edit a notebook it never saw, or edit against a
        # stale view after an external change — silent data loss.
        read_state = _read_file_state(context)
        read_timestamp = read_state.get(full_path)
        if not read_timestamp:
            return ValidationResult.fail(
                "File has not been read yet. Read it first before writing to it.", error_code=9
            )
        if get_file_modification_time(full_path) > read_timestamp["timestamp"]:
            return ValidationResult.fail(
                "File has been modified since read, either by the user or by a linter. "
                "Read it again before attempting to write it.",
                error_code=10,
            )

        try:
            content = read_file_sync_with_metadata(full_path)["content"]
        except OSError as e:
            if is_enoent_error(e):
                return ValidationResult.fail("Notebook file does not exist.", error_code=1)
            raise

        notebook = safe_parse_json(content)
        if notebook is None:
            return ValidationResult.fail("Notebook is not valid JSON.", error_code=6)

        cells = notebook.get("cells") or []
        if not cell_id:
            if edit_mode != "insert":
                return ValidationResult.fail(
                    "Cell ID must be specified when not inserting a new cell.", error_code=7
                )
        else:
            # First try to find the cell by its actual ID
            cell_index = _find_cell_index(cells, cell_id)
            if cell_index == -1:
                # If not found, try to parse as a numeric index (cell-N format)
                parsed_cell_index = parse_cell_id(cell_id)
                if parsed_cell_index is not None:
                    if parsed_cell_index >= len(cells):
                        return ValidationResult.fail(
                            f"Cell with index {parsed_cell_index} does not exist in notebook.",
                            error_code=7,
                        )
                else:
                    return ValidationResult.fail(
                        f'Cell with ID "{cell_id}" not found in notebook.', error_code=8
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
        notebook_path = input["notebook_path"]
        new_source = input["new_source"]
        cell_id = input.get("cell_id")
        cell_type = input.get("cell_type")
        original_edit_mode = input.get("edit_mode", "replace")

        full_path = expand_path(notebook_path)

        # RE-ENTRY: fileHistory hook. When fileHistory is ported:
        #   if file_history_enabled():
        #       await file_history_track_edit(context.update_file_history_state, full_path, parent_message.uuid)
        # Until then this is a no-op (matches FileEditTool/FileWriteTool).

        try:
            meta = read_file_sync_with_metadata(full_path)
            content = meta["content"]
            encoding = meta["encoding"]
            line_endings = meta["line_endings"]

            # Must use the non-memoized json_parse here: safe_parse_json caches by
            # content string and returns a shared object reference, but we mutate
            # the notebook in place below (cells.insert, target_cell["source"]=...).
            # Using the memoized version would poison the cache for validate_input()
            # and any subsequent call() with the same file content.
            try:
                notebook = json_parse(content)
            except (ValueError, TypeError):
                return ToolResult(
                    data={
                        "new_source": new_source,
                        "cell_type": cell_type or "code",
                        "language": "python",
                        "edit_mode": "replace",
                        "error": "Notebook is not valid JSON.",
                        "cell_id": cell_id,
                        "notebook_path": full_path,
                        "original_file": "",
                        "updated_file": "",
                    }
                )

            cells: list[dict[str, Any]] = notebook.get("cells") or []

            if not cell_id:
                cell_index = 0  # Default to inserting at the beginning if no cell_id is provided
            else:
                # First try to find the cell by its actual ID
                cell_index = _find_cell_index(cells, cell_id)
                # If not found, try to parse as a numeric index (cell-N format)
                if cell_index == -1:
                    parsed_cell_index = parse_cell_id(cell_id)
                    if parsed_cell_index is not None:
                        cell_index = parsed_cell_index
                if original_edit_mode == "insert":
                    cell_index += 1  # Insert after the cell with this ID

            # Convert replace to insert if trying to replace one past the end
            edit_mode = original_edit_mode
            if edit_mode == "replace" and cell_index == len(cells):
                edit_mode = "insert"
                if not cell_type:
                    cell_type = "code"  # Default to code if no cell_type specified

            metadata = notebook.get("metadata") or {}
            language_info = metadata.get("language_info") or {}
            language = language_info.get("name") or "python"

            new_cell_id: Optional[str] = None
            nbformat = notebook.get("nbformat") or 0
            nbformat_minor = notebook.get("nbformat_minor") or 0
            if nbformat > 4 or (nbformat == 4 and nbformat_minor >= 5):
                if edit_mode == "insert":
                    new_cell_id = _new_random_cell_id()
                elif cell_id is not None:
                    new_cell_id = cell_id

            if edit_mode == "delete":
                # Delete the specified cell
                del cells[cell_index]
            elif edit_mode == "insert":
                if cell_type == "markdown":
                    new_cell: dict[str, Any] = {
                        "cell_type": "markdown",
                        "id": new_cell_id,
                        "source": new_source,
                        "metadata": {},
                    }
                else:
                    new_cell = {
                        "cell_type": "code",
                        "id": new_cell_id,
                        "source": new_source,
                        "metadata": {},
                        "execution_count": None,
                        "outputs": [],
                    }
                # Insert the new cell
                cells.insert(cell_index, new_cell)
            else:
                # Find the specified cell (validate_input ensures cell_index is in bounds)
                target_cell = cells[cell_index]
                target_cell["source"] = new_source
                if target_cell.get("cell_type") == "code":
                    # Reset execution count and clear outputs since cell was modified
                    target_cell["execution_count"] = None
                    target_cell["outputs"] = []
                if cell_type and cell_type != target_cell.get("cell_type"):
                    target_cell["cell_type"] = cell_type

            # Write back to file
            updated_content = json_stringify(notebook, None, _IPYNB_INDENT)
            write_text_content(full_path, updated_content, encoding, line_endings)

            # Update readFileState with post-write mtime (matches FileEditTool/
            # FileWriteTool). offset=None breaks FileReadTool's dedup match —
            # without this, Read→NotebookEdit→Read in the same millisecond would
            # return the file_unchanged stub against stale in-context content.
            read_state = _read_file_state(context)
            read_state[full_path] = {
                "content": updated_content,
                "timestamp": get_file_modification_time(full_path),
                "offset": None,
                "limit": None,
            }

            return ToolResult(
                data={
                    "new_source": new_source,
                    "cell_type": cell_type or "code",
                    "language": language,
                    "edit_mode": edit_mode or "replace",
                    "cell_id": new_cell_id or None,
                    "error": "",
                    "notebook_path": full_path,
                    "original_file": content,
                    "updated_file": updated_content,
                }
            )
        except Exception as error:
            # Mirrors the TS catch: Error → error.message, else a generic message.
            if isinstance(error, Exception):
                msg = str(error)
            else:
                msg = "Unknown error occurred while editing notebook"
            return ToolResult(
                data={
                    "new_source": new_source,
                    "cell_type": cell_type or "code",
                    "language": "python",
                    "edit_mode": "replace",
                    "error": msg,
                    "cell_id": cell_id,
                    "notebook_path": full_path,
                    "original_file": "",
                    "updated_file": "",
                }
            )
