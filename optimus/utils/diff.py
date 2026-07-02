"""
utils/diff.py — partial port of src/utils/diff.ts

Structured patch generation + line-change accounting. get_patch_for_display
builds unified-diff "hunks"; count_lines_changed tallies added/removed lines into
bootstrap state.

Porting note: the TS uses the `diff` library's structuredPatch. This port uses
Python's difflib.unified_diff and parses it into the same hunk shape:
  {oldStart, oldLines, newStart, newLines, lines: [...]}.
"""
from __future__ import annotations

import difflib
from typing import Any, Optional

Hunk = dict[str, Any]


def structured_patch(old_str: str, new_str: str, file_name: str = "file") -> list[Hunk]:
    """Build unified-diff hunks from old→new content."""
    old_lines = old_str.split("\n")
    new_lines = new_str.split("\n")
    diff = list(
        difflib.unified_diff(old_lines, new_lines, lineterm="", n=3)
    )
    hunks: list[Hunk] = []
    current: Optional[Hunk] = None
    for line in diff:
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("@@"):
            # @@ -oldStart,oldLines +newStart,newLines @@
            import re

            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                current = {
                    "oldStart": int(m.group(1)),
                    "oldLines": int(m.group(2) or 1),
                    "newStart": int(m.group(3)),
                    "newLines": int(m.group(4) or 1),
                    "lines": [],
                }
                hunks.append(current)
            continue
        if current is not None:
            current["lines"].append(line)
    return hunks


def get_patch_for_display(
    *,
    file_path: str,
    file_contents: str,
    edits: list[dict[str, Any]],
) -> list[Hunk]:
    """
    Apply the edits in-memory and return the structured patch old→new.
    Mirrors getPatchForDisplay() for the single-file case.
    """
    new_contents = file_contents
    for edit in edits:
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        if edit.get("replace_all"):
            new_contents = new_contents.replace(old_string, new_string)
        else:
            new_contents = new_contents.replace(old_string, new_string, 1)
    return structured_patch(file_contents, new_contents, file_path)


def count_lines_changed(patch: list[Hunk], created_content: Optional[str] = None) -> None:
    """
    Tally added/removed lines into bootstrap state. For new files, pass the full
    content as created_content (all lines counted as additions).
    """
    from optimus.bootstrap.state import add_to_total_lines_changed

    if created_content is not None:
        added = len(created_content.split("\n")) if created_content else 0
        add_to_total_lines_changed(added, 0)
        return

    added = 0
    removed = 0
    for hunk in patch:
        for line in hunk["lines"]:
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    add_to_total_lines_changed(added, removed)
