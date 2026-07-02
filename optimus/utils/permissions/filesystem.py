"""
utils/permissions/filesystem.py — partial port of src/utils/permissions/filesystem.ts

path_in_working_path mirrors pathInWorkingPath: is `path` inside `working_path`,
with macOS /private symlink normalization and case-insensitive comparison on
case-insensitive filesystems.
"""
from __future__ import annotations

import os
import re
import sys

from optimus.utils.path import contains_path_traversal, expand_path


def _normalize_private_symlinks(p: str) -> str:
    p = re.sub(r"^/private/var/", "/var/", p)
    p = re.sub(r"^/private/tmp(/|$)", r"/tmp\1", p)
    return p


def _normalize_case_for_comparison(p: str) -> str:
    # Case-insensitive on macOS/Windows.
    return p.lower() if sys.platform in ("win32", "darwin") else p


def path_in_working_path(path: str, working_path: str) -> bool:
    absolute_path = expand_path(path)
    absolute_working_path = expand_path(working_path)

    normalized_path = _normalize_private_symlinks(absolute_path)
    normalized_working_path = _normalize_private_symlinks(absolute_working_path)

    case_path = _normalize_case_for_comparison(normalized_path)
    case_working = _normalize_case_for_comparison(normalized_working_path)

    try:
        rel = os.path.relpath(case_path, case_working)
    except ValueError:
        # Cross-drive on Windows — not contained.
        return False

    if rel == "" or rel == ".":
        return True
    if contains_path_traversal(rel):
        return False
    return True
