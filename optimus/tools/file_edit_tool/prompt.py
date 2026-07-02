"""tools/file_edit_tool/prompt.py — port of src/tools/FileEditTool/prompt.ts"""
from __future__ import annotations

FILE_EDIT_TOOL_NAME = "Edit"

_FILE_READ_TOOL_NAME = "Read"


def get_edit_tool_description() -> str:
    pre_read = (
        f"\n- You must use your `{_FILE_READ_TOOL_NAME}` tool at least once in the "
        "conversation before editing. This tool will error if you attempt an edit "
        "without reading the file. "
    )
    return f"""Performs exact string replacements in files.

Usage:{pre_read}
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + arrow. Everything after that is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."""
