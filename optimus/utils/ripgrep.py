"""
utils/ripgrep.py — port of src/utils/ripgrep.ts (ripGrep helper)

ripGrep runs the `rg` binary and returns its stdout lines. When `rg` is not on
PATH, a pure-Python fallback emulates the subset of flags GrepTool uses:
  pattern (or `-e pattern`), -i, -l, -c, -n, -C/-A/-B N, -U multiline,
  --glob <inc>/!<exc>, --hidden, --max-columns, --type (mapped to extensions).

Porting notes:
  - Fallback line formats match rg: content → `path:lineno:line` (with -n) or
    `path:line`; files_with_matches (-l) → `path`; count (-c) → `path:count`.
    Context lines (-A/-B/-C) are emitted as `path:lineno:line` too (rg uses a
    `-` separator; simplified here so GrepTool's first-colon split still works).
  - RipgrepTimeoutError → subprocess timeout raises TimeoutError.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Optional

import pathspec

# rg --type name → file extensions (common subset).
_TYPE_EXTENSIONS: dict[str, list[str]] = {
    "js": [".js", ".jsx", ".mjs", ".cjs"],
    "ts": [".ts", ".tsx", ".mts", ".cts"],
    "py": [".py", ".pyi", ".pyw"],
    "rust": [".rs"],
    "go": [".go"],
    "java": [".java"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".hxx"],
    "md": [".md", ".markdown"],
    "json": [".json"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss", ".sass", ".less"],
    "sh": [".sh", ".bash", ".zsh"],
}


class RipgrepTimeoutError(Exception):
    """Mirrors RipgrepTimeoutError — rg exceeded its time budget."""


def _run_rg_binary(args: list[str], target: str) -> Optional[list[str]]:
    rg = shutil.which("rg")
    if not rg:
        return None
    try:
        proc = subprocess.run(
            [rg, *args, target] if os.path.isdir(target) or os.path.isfile(target) else [rg, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise RipgrepTimeoutError(str(e))
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):  # 1 = no matches
        return None
    return [line for line in proc.stdout.split("\n") if line != ""]


class _ParsedArgs:
    def __init__(self) -> None:
        self.pattern: Optional[str] = None
        self.ignore_case = False
        self.files_with_matches = False
        self.count = False
        self.line_numbers = False
        self.multiline = False
        self.before = 0
        self.after = 0
        self.max_columns: Optional[int] = None
        self.include_globs: list[str] = []
        self.exclude_globs: list[str] = []
        self.types: list[str] = []


def _parse_args(args: list[str]) -> _ParsedArgs:
    p = _ParsedArgs()
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-i":
            p.ignore_case = True
        elif a == "-l":
            p.files_with_matches = True
        elif a == "-c":
            p.count = True
        elif a == "-n":
            p.line_numbers = True
        elif a in ("-U", "--multiline-dotall"):
            p.multiline = True
        elif a == "--hidden":
            pass
        elif a == "-C":
            i += 1
            p.before = p.after = int(args[i])
        elif a == "-B":
            i += 1
            p.before = int(args[i])
        elif a == "-A":
            i += 1
            p.after = int(args[i])
        elif a == "--max-columns":
            i += 1
            p.max_columns = int(args[i])
        elif a == "--glob":
            i += 1
            g = args[i]
            if g.startswith("!"):
                p.exclude_globs.append(g[1:])
            else:
                p.include_globs.append(g)
        elif a == "--type":
            i += 1
            p.types.append(args[i])
        elif a == "-e":
            i += 1
            p.pattern = args[i]
        elif not a.startswith("-") and p.pattern is None:
            p.pattern = a
        i += 1
    return p


def _iter_files(target: str, p: _ParsedArgs):
    inc_spec = pathspec.PathSpec.from_lines("gitwildmatch", p.include_globs) if p.include_globs else None
    exc_spec = pathspec.PathSpec.from_lines("gitwildmatch", p.exclude_globs) if p.exclude_globs else None
    type_exts: list[str] = []
    for t in p.types:
        type_exts.extend(_TYPE_EXTENSIONS.get(t, []))

    if os.path.isfile(target):
        yield target
        return

    for root, dirs, files in os.walk(target):
        for name in files:
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, target).replace(os.sep, "/")
            if exc_spec and exc_spec.match_file(rel):
                continue
            if inc_spec and not inc_spec.match_file(rel):
                continue
            if type_exts and os.path.splitext(name)[1] not in type_exts:
                continue
            yield abs_path


def _python_fallback(args: list[str], target: str) -> list[str]:
    p = _parse_args(args)
    if p.pattern is None:
        return []
    flags = re.MULTILINE
    if p.ignore_case:
        flags |= re.IGNORECASE
    if p.multiline:
        flags |= re.DOTALL
    try:
        regex = re.compile(p.pattern, flags)
    except re.error:
        return []

    out: list[str] = []
    for abs_path in _iter_files(target, p):
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if "\0" in text[:1024]:  # crude binary skip
            continue

        if p.multiline:
            if not regex.search(text):
                continue
            matched_line_idxs = set()
            for m in regex.finditer(text):
                start_line = text.count("\n", 0, m.start())
                matched_line_idxs.add(start_line)
            lines = text.split("\n")
        else:
            lines = text.split("\n")
            matched_line_idxs = {idx for idx, line in enumerate(lines) if regex.search(line)}
            if not matched_line_idxs:
                continue

        if p.files_with_matches:
            out.append(abs_path)
            continue
        if p.count:
            out.append(f"{abs_path}:{len(matched_line_idxs)}")
            continue

        # content mode (with optional context)
        emit_idxs: set[int] = set()
        for idx in matched_line_idxs:
            for j in range(idx - p.before, idx + p.after + 1):
                if 0 <= j < len(lines):
                    emit_idxs.add(j)
        for idx in sorted(emit_idxs):
            line = lines[idx]
            if p.max_columns and len(line) > p.max_columns:
                line = line[: p.max_columns]
            if p.line_numbers:
                out.append(f"{abs_path}:{idx + 1}:{line}")
            else:
                out.append(f"{abs_path}:{line}")
    return out


async def rip_grep(args: list[str], target: str, abort_event: Any = None) -> list[str]:
    """Run ripgrep (or the Python fallback) and return stdout lines."""
    result = _run_rg_binary(args, target)
    if result is not None:
        return result
    return _python_fallback(args, target)
