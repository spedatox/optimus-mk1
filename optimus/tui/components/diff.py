"""
optimus/tui/components/diff.py

Port of: components/StructuredDiff/Fallback.tsx (StructuredDiffFallback).

The primary StructuredDiff renderer in the source delegates to a Rust NAPI
module (colorDiff) for syntax-highlighted diffs; the TypeScript fallback is
the portable specification and what this module implements:

  1. transformLinesToObjects: '+'/'-'/' ' prefixed patch lines → typed rows.
  2. processAdjacentLines:   pair each run of remove-lines with the following
     run of add-lines (k-th remove ↔ k-th add) for word-level diffing.
  3. numberDiffLines:        assign line numbers starting at old_start;
     paired add lines reuse the row number of their removed counterpart.
  4. Render: `<lineno> <sigil><code>` padded to full width, with:
       - full-line background diffAdded #225c2b / diffRemoved #7a2936
       - word-level highlight diffAddedWord #38a660 / diffRemovedWord #b35960
         on the changed tokens only, when the changed fraction of the paired
         lines is ≤ CHANGE_THRESHOLD (0.4); above that, whole-line rendering
       - dimmed variants diffAddedDimmed #47584a / diffRemovedDimmed #69484d

diffWordsWithSpace (jsdiff) is replaced by difflib.SequenceMatcher over a
words-and-whitespace tokenisation, which produces the same added/removed/
common part stream.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

# darkTheme diff colours (utils/theme.ts)
DIFF_ADDED          = "#225c2b"
DIFF_REMOVED        = "#7a2936"
DIFF_ADDED_DIMMED   = "#47584a"
DIFF_REMOVED_DIMMED = "#69484d"
DIFF_ADDED_WORD     = "#38a660"
DIFF_REMOVED_WORD   = "#b35960"
TEXT_COLOUR         = "#ffffff"
INACTIVE            = "#999999"

# Fallback.tsx: threshold for word-level vs whole-line rendering
CHANGE_THRESHOLD = 0.4


@dataclass
class LineObject:
    """Fallback.tsx LineObject."""
    code: str
    type: str                        # 'add' | 'remove' | 'nochange'
    i: int = 0
    original_code: str = ""
    word_diff: bool = False
    matched_line: Optional["LineObject"] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Steps 1–3 — direct ports of the exported helpers
# ---------------------------------------------------------------------------

def transform_lines_to_objects(lines: list[str]) -> list[LineObject]:
    out: list[LineObject] = []
    for code in lines:
        if code.startswith("+"):
            t = "add"
        elif code.startswith("-"):
            t = "remove"
        else:
            t = "nochange"
        body = code[1:]
        out.append(LineObject(code=body, type=t, original_code=body))
    return out


def process_adjacent_lines(line_objects: list[LineObject]) -> list[LineObject]:
    processed: list[LineObject] = []
    i = 0
    n = len(line_objects)
    while i < n:
        current = line_objects[i]
        if current.type == "remove":
            remove_lines = [current]
            j = i + 1
            while j < n and line_objects[j].type == "remove":
                remove_lines.append(line_objects[j])
                j += 1
            add_lines: list[LineObject] = []
            while j < n and line_objects[j].type == "add":
                add_lines.append(line_objects[j])
                j += 1
            if remove_lines and add_lines:
                for k in range(min(len(remove_lines), len(add_lines))):
                    remove_lines[k].word_diff = True
                    add_lines[k].word_diff = True
                    remove_lines[k].matched_line = add_lines[k]
                    add_lines[k].matched_line = remove_lines[k]
                processed.extend(remove_lines)
                processed.extend(add_lines)
                i = j
            else:
                processed.append(current)
                i += 1
        else:
            processed.append(current)
            i += 1
    return processed


def number_diff_lines(diff: list[LineObject], start_line: int) -> list[LineObject]:
    """numberDiffLines: nochange/add advance the counter; a run of removes is
    numbered from the pre-run counter (the removed lines' old positions)."""
    i = start_line
    result: list[LineObject] = []
    queue = list(diff)
    while queue:
        current = queue.pop(0)
        line = LineObject(
            code=current.code, type=current.type, i=i,
            original_code=current.original_code,
            word_diff=current.word_diff, matched_line=current.matched_line,
        )
        if current.type in ("nochange", "add"):
            i += 1
            result.append(line)
        else:  # remove
            result.append(line)
            while queue and queue[0].type == "remove":
                i += 1
                nxt = queue.pop(0)
                result.append(LineObject(
                    code=nxt.code, type=nxt.type, i=i,
                    original_code=nxt.original_code,
                    word_diff=nxt.word_diff, matched_line=nxt.matched_line,
                ))
    return result


# ---------------------------------------------------------------------------
# Word-level diff — diffWordsWithSpace equivalent
# ---------------------------------------------------------------------------

def calculate_word_diffs(old_text: str, new_text: str) -> list[dict]:
    """Returns [{'value': str, 'added': bool, 'removed': bool}, ...] in
    document order, whitespace-preserving (tokens are words OR runs of
    whitespace, like jsdiff's diffWordsWithSpace)."""
    tokenize = lambda s: re.findall(r"\S+|\s+", s)
    old_tokens = tokenize(old_text)
    new_tokens = tokenize(new_text)
    sm = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    parts: list[dict] = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            parts.append({"value": "".join(old_tokens[a0:a1]), "added": False, "removed": False})
        elif op == "delete":
            parts.append({"value": "".join(old_tokens[a0:a1]), "added": False, "removed": True})
        elif op == "insert":
            parts.append({"value": "".join(new_tokens[b0:b1]), "added": True, "removed": False})
        else:  # replace → removed part then added part (jsdiff order)
            parts.append({"value": "".join(old_tokens[a0:a1]), "added": False, "removed": True})
            parts.append({"value": "".join(new_tokens[b0:b1]), "added": True, "removed": False})
    return parts


def _escape(s: str) -> str:
    """Escape Rich markup delimiters in code content."""
    return s.replace("[", r"\[")


# ---------------------------------------------------------------------------
# Step 4 — rendering to Rich markup lines
# ---------------------------------------------------------------------------

def _render_word_diff_line(item: LineObject, max_width: int, width: int) -> Optional[str]:
    """generateWordDiffElements (single-line, no wrap — Textual wraps for us).
    Returns None when the change ratio exceeds the threshold (caller falls
    back to whole-line rendering)."""
    if not item.word_diff or item.matched_line is None:
        return None
    removed_text = item.original_code if item.type == "remove" else item.matched_line.original_code
    added_text = item.matched_line.original_code if item.type == "remove" else item.original_code
    word_diffs = calculate_word_diffs(removed_text, added_text)

    total_length = len(removed_text) + len(added_text)
    changed_length = sum(len(p["value"]) for p in word_diffs if p["added"] or p["removed"])
    if total_length == 0 or (changed_length / total_length) > CHANGE_THRESHOLD:
        return None

    prefix = "+" if item.type == "add" else "-"
    line_bg = DIFF_ADDED if item.type == "add" else DIFF_REMOVED
    word_bg = DIFF_ADDED_WORD if item.type == "add" else DIFF_REMOVED_WORD

    segments: list[str] = []
    content_len = 0
    for part in word_diffs:
        if item.type == "add":
            if part["added"]:
                bg = word_bg
            elif not part["removed"]:
                bg = line_bg
            else:
                continue
        else:
            if part["removed"]:
                bg = word_bg
            elif not part["added"]:
                bg = line_bg
            else:
                continue
        segments.append(f"[{TEXT_COLOUR} on {bg}]{_escape(part['value'])}[/]")
        content_len += len(part["value"])

    line_num_str = str(item.i).rjust(max_width) + " "
    used = len(line_num_str) + 1 + content_len
    padding = " " * max(0, width - used)
    gutter = f"[{TEXT_COLOUR} on {line_bg}]{line_num_str}{prefix}[/]"
    return gutter + "".join(segments) + f"[on {line_bg}]{padding}[/]"


def format_structured_diff(
    lines: list[str],
    old_start: int,
    width: int = 80,
    dim: bool = False,
) -> list[str]:
    """formatDiff — returns one Rich-markup string per rendered diff row."""
    safe_width = max(1, int(width))
    line_objects = transform_lines_to_objects(lines)
    processed = process_adjacent_lines(line_objects)
    numbered = number_diff_lines(processed, old_start)

    max_line_number = max([lo.i for lo in numbered], default=0)
    max_width = max(len(str(max_line_number)) + 1, 0)

    rendered: list[str] = []
    for item in numbered:
        if item.word_diff and item.matched_line is not None and not dim:
            word_line = _render_word_diff_line(item, max_width, safe_width)
            if word_line is not None:
                rendered.append(word_line)
                continue

        # Standard whole-line rendering
        line_num_str = str(item.i).rjust(max_width) + " "
        sigil = "+" if item.type == "add" else "-" if item.type == "remove" else " "
        if item.type == "add":
            bg = DIFF_ADDED_DIMMED if dim else DIFF_ADDED
        elif item.type == "remove":
            bg = DIFF_REMOVED_DIMMED if dim else DIFF_REMOVED
        else:
            bg = None
        content_width = len(line_num_str) + 1 + len(item.code)
        padding = " " * max(0, safe_width - content_width)
        if bg:
            rendered.append(
                f"[{TEXT_COLOUR} on {bg}]{line_num_str}{sigil}{_escape(item.code)}{padding}[/]"
            )
        else:
            rendered.append(
                f"[{INACTIVE}]{line_num_str}{sigil}[/{INACTIVE}]{_escape(item.code)}"
            )
    return rendered


# ---------------------------------------------------------------------------
# Convenience: build patch hunks from old/new strings (Edit tool previews).
# Mirrors what FileEditTool does with jsdiff structuredPatch before handing
# hunks to StructuredDiff.
# ---------------------------------------------------------------------------

def build_patch_lines(old_string: str, new_string: str) -> tuple[list[str], int]:
    """Returns (patch_lines with +/-/space prefixes, old_start). Uses a
    3-line context window like structuredPatch's default."""
    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    groups = sm.get_grouped_opcodes(3)
    out: list[str] = []
    old_start = 1
    first = True
    for group in groups:
        for op, a0, a1, b0, b1 in group:
            if first:
                old_start = a0 + 1
                first = False
            if op == "equal":
                out.extend(" " + l for l in old_lines[a0:a1])
            elif op == "delete":
                out.extend("-" + l for l in old_lines[a0:a1])
            elif op == "insert":
                out.extend("+" + l for l in new_lines[b0:b1])
            else:  # replace
                out.extend("-" + l for l in old_lines[a0:a1])
                out.extend("+" + l for l in new_lines[b0:b1])
        break  # first hunk only for permission previews
    return out, old_start


def render_edit_diff(old_string: str, new_string: str, width: int = 72) -> str:
    """One-call helper for Edit/Write permission previews: word-level diff
    of old_string → new_string as a single Rich-markup block."""
    patch_lines, old_start = build_patch_lines(old_string, new_string)
    if not patch_lines:
        return ""
    return "\n".join(format_structured_diff(patch_lines, old_start, width))
