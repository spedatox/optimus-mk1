"""tools/file_read_tool/prompt.py — port of src/tools/FileReadTool/prompt.ts"""
from __future__ import annotations

FILE_READ_TOOL_NAME = "Read"

FILE_UNCHANGED_STUB = (
    "File unchanged since last read. The content from the earlier Read tool_result "
    "in this conversation is still current — refer to that instead of re-reading."
)

MAX_LINES_TO_READ = 2000
DESCRIPTION = "Read a file from the local filesystem."

LINE_FORMAT_INSTRUCTION = (
    "- Results are returned using cat -n format, with line numbers starting at 1"
)

_BASH_TOOL_NAME = "Bash"


def get_read_tool_description() -> str:
    return f"""Reads a file from the local filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to {MAX_LINES_TO_READ} lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
{LINE_FORMAT_INSTRUCTION}
- This tool can read images and Jupyter notebooks (.ipynb).
- This tool can only read files, not directories. To read a directory, use an ls command via the {_BASH_TOOL_NAME} tool.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents."""
