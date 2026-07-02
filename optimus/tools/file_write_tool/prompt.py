"""tools/file_write_tool/prompt.py — port of src/tools/FileWriteTool/prompt.ts"""
from __future__ import annotations

FILE_WRITE_TOOL_NAME = "Write"


def get_write_tool_description() -> str:
    return (
        "Writes a file to the local filesystem.\n\n"
        "When to use: creating a new file, or fully replacing one you've already "
        "Read. Overwriting an existing file you haven't Read will fail. For partial "
        "changes, use Edit instead."
    )
