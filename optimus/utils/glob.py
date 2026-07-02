"""
utils/glob.py — port of src/utils/glob.ts

File pattern matching. The TS version shells out to ripgrep (`rg --files --glob
... --sort=modified`); this port does the same when `rg` is on PATH, and
otherwise falls back to a pure-Python walk (pathspec for matching, mtime sort).

Porting notes:
  - ripGrep subprocess → subprocess when `rg` exists, else Python fallback.
  - getFileReadIgnorePatterns / normalizePatternsToPath / plugin-cache
    exclusions → RE-ENTRY stubs (return []) until permissions/plugins are ported.
  - --sort=modified → sort by st_mtime ascending (oldest first), matching rg.
  - --hidden default true, --no-ignore default true → both honored
    (CLAUDE_CODE_GLOB_HIDDEN / CLAUDE_CODE_GLOB_NO_IGNORE).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Optional

import pathspec

from optimus.env_utils import is_env_truthy


def extract_glob_base_directory(pattern: str) -> dict[str, str]:
    """
    Split a glob into its static base directory and the remaining relative
    pattern. Returns {'baseDir', 'relativePattern'}. Faithful to glob.ts.
    """
    match = re.search(r"[*?\[{]", pattern)
    if not match:
        # Literal path — directory + filename.
        return {"baseDir": os.path.dirname(pattern), "relativePattern": os.path.basename(pattern)}

    static_prefix = pattern[: match.start()]
    last_sep_index = max(static_prefix.rfind("/"), static_prefix.rfind(os.sep))

    if last_sep_index == -1:
        return {"baseDir": "", "relativePattern": pattern}

    base_dir = static_prefix[:last_sep_index]
    relative_pattern = pattern[last_sep_index + 1 :]

    if base_dir == "" and last_sep_index == 0:
        base_dir = "/"

    if os.name == "nt" and re.match(r"^[A-Za-z]:$", base_dir):
        base_dir = base_dir + os.sep

    return {"baseDir": base_dir, "relativePattern": relative_pattern}


def _get_file_read_ignore_patterns(_ctx: Any) -> list[str]:
    """Stub — mirrors getFileReadIgnorePatterns() (permissions/filesystem.ts)."""
    # RE-ENTRY: from optimus.utils.permissions.filesystem import get_file_read_ignore_patterns
    return []


async def _get_glob_exclusions_for_plugin_cache(_search_dir: str) -> list[str]:
    """Stub — mirrors getGlobExclusionsForPluginCache() (plugins)."""
    return []


def _ripgrep_files(args: list[str], cwd: str) -> Optional[list[str]]:
    """Run `rg` and return relative paths, or None if rg is unavailable/fails."""
    rg = shutil.which("rg")
    if not rg:
        return None
    try:
        proc = subprocess.run(
            [rg, *args], cwd=cwd, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):  # 1 = no matches
        return None
    return [line for line in proc.stdout.split("\n") if line]


def _python_glob_files(
    search_dir: str, search_pattern: str, hidden: bool
) -> list[str]:
    """
    Fallback file listing: walk search_dir, match relative paths against the
    glob via pathspec, return sorted by mtime (oldest first, like --sort=modified).
    """
    spec = pathspec.PathSpec.from_lines("gitwildmatch", [search_pattern])
    matches: list[tuple[float, str]] = []
    for root, dirs, files in os.walk(search_dir):
        if not hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not hidden and name.startswith("."):
                continue
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, search_dir).replace(os.sep, "/")
            if spec.match_file(rel):
                try:
                    mtime = os.stat(abs_path).st_mtime
                except OSError:
                    mtime = 0.0
                matches.append((mtime, rel))
    matches.sort(key=lambda t: t[0])  # oldest first
    return [rel for _, rel in matches]


async def glob(
    file_pattern: str,
    cwd: str,
    limits: dict[str, int],
    abort_event: Any,
    tool_permission_context: Any,
) -> dict[str, Any]:
    """Return {'files': [...absolute...], 'truncated': bool}."""
    limit = limits.get("limit", 100)
    offset = limits.get("offset", 0)

    search_dir = cwd
    search_pattern = file_pattern

    if os.path.isabs(file_pattern):
        parts = extract_glob_base_directory(file_pattern)
        if parts["baseDir"]:
            search_dir = parts["baseDir"]
            search_pattern = parts["relativePattern"]

    hidden = is_env_truthy(os.environ.get("CLAUDE_CODE_GLOB_HIDDEN") or "true")
    no_ignore = is_env_truthy(os.environ.get("CLAUDE_CODE_GLOB_NO_IGNORE") or "true")

    # Faithful path: ripgrep, when available.
    args = ["--files", "--glob", search_pattern, "--sort=modified"]
    if no_ignore:
        args.append("--no-ignore")
    if hidden:
        args.append("--hidden")
    for pattern in _get_file_read_ignore_patterns(tool_permission_context):
        args += ["--glob", f"!{pattern}"]
    for exclusion in await _get_glob_exclusions_for_plugin_cache(search_dir):
        args += ["--glob", exclusion]

    all_paths = _ripgrep_files(args, search_dir)
    if all_paths is None:
        all_paths = _python_glob_files(search_dir, search_pattern, hidden)

    absolute_paths = [
        p if os.path.isabs(p) else os.path.join(search_dir, p) for p in all_paths
    ]

    truncated = len(absolute_paths) > offset + limit
    files = absolute_paths[offset : offset + limit]
    return {"files": files, "truncated": truncated}
