"""
utils/file.py — partial port of src/utils/file.ts

normalize_path_for_comparison mirrors normalizePathForComparison: clean up
separators + resolve . / .., and on Windows lowercase + backslash-normalize for
case-insensitive comparison.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

# Mirrors FILE_NOT_FOUND_CWD_NOTE from file.ts — appended to "not found" messages.
FILE_NOT_FOUND_CWD_NOTE = "The current working directory is"

# Mirrors MAX_OUTPUT_SIZE from file.ts — 0.25MB byte cap for full text reads.
MAX_OUTPUT_SIZE = int(0.25 * 1024 * 1024)


def add_line_numbers(content: str, start_line: int) -> str:
    """
    Port of addLineNumbers() — cat -n format: right-padded 6-wide line number,
    a `→` separator, then the line. start_line is 1-indexed.
    """
    if not content:
        return ""
    import re as _re

    lines = _re.split(r"\r?\n", content)
    out = []
    for index, line in enumerate(lines):
        num_str = str(index + start_line)
        if len(num_str) >= 6:
            out.append(f"{num_str}→{line}")
        else:
            out.append(f"{num_str.rjust(6)}→{line}")
    return "\n".join(out)


def normalize_path_for_comparison(file_path: str) -> str:
    normalized = os.path.normpath(file_path)
    if sys.platform == "win32":
        normalized = normalized.replace("/", "\\").lower()
    return normalized


async def suggest_path_under_cwd(absolute_path: str) -> Optional[str]:
    """
    Partial port of suggestPathUnderCwd() — suggest a same-basename path that
    actually exists under cwd. The full fuzzy-match heuristic is RE-ENTRY; this
    covers the common "right name, wrong directory" case.
    """
    from optimus.utils.cwd import get_cwd

    base = os.path.basename(absolute_path)
    if not base:
        return None
    candidate = os.path.join(get_cwd(), base)
    if os.path.exists(candidate) and candidate != absolute_path:
        return candidate
    return None


def get_display_path(file_path: str) -> str:
    """
    Port of getDisplayPath() — choose the shortest human-friendly form:
    a cwd-relative path when the file lives under cwd, a tilde path when it
    lives under the home directory, otherwise the absolute path verbatim.
    """
    from optimus.utils.cwd import get_cwd
    from optimus.utils.path import expand_path

    absolute_path = expand_path(file_path)
    try:
        relative_path = os.path.relpath(absolute_path, get_cwd())
    except ValueError:
        relative_path = None  # cross-drive on Windows
    if relative_path and not relative_path.startswith(".."):
        return relative_path

    home = os.path.expanduser("~")
    if file_path.startswith(home + os.sep):
        return "~" + file_path[len(home):]

    return file_path


def get_file_modification_time(file_path: str) -> int:
    """Port of getFileModificationTime() — mtime in epoch milliseconds (0 if missing)."""
    try:
        return int(os.stat(file_path).st_mtime * 1000)
    except OSError:
        return 0


def write_text_content(file_path: str, content: str, encoding: str = "utf-8", line_ending: str = "LF") -> None:
    """
    Port of writeTextContent() — write text with the requested line ending.
    The model's content is taken verbatim; only the EOL convention is applied.
    """
    normalized = content.replace("\r\n", "\n")
    if line_ending == "CRLF":
        normalized = normalized.replace("\n", "\r\n")
    enc = "utf-8" if encoding in ("utf8", "utf-8") else encoding
    with open(file_path, "w", encoding=enc, newline="") as f:
        f.write(normalized)
