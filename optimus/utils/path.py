"""
utils/path.py — partial port of src/utils/path.ts

normalize_path_for_config_key mirrors normalizePathForConfigKey: resolve . and
.. segments, then convert backslashes to forward slashes so Windows and POSIX
paths map to the same JSON config key.
"""
from __future__ import annotations

import os
import posixpath
import unicodedata
from pathlib import Path
from typing import Optional


def normalize_path_for_config_key(path: str) -> str:
    # Resolve '.' and '..' segments lexically (Node path.normalize), then force
    # forward slashes for stable JSON keys across platforms.
    normalized = posixpath.normpath(path.replace("\\", "/"))
    return normalized.replace("\\", "/")


def expand_path(path: str, base_dir: Optional[str] = None) -> str:
    """
    Port of expandPath() from src/utils/path.ts. Resolve ~, absolute, and
    relative paths to an absolute path (NFC-normalized).
    """
    from optimus.utils.cwd import get_cwd

    actual_base_dir = base_dir if base_dir is not None else get_cwd()
    if not isinstance(path, str):
        raise TypeError(f"Path must be a string, received {type(path)}")
    if "\0" in path or "\0" in actual_base_dir:
        raise ValueError("Path contains null bytes")

    trimmed = path.strip()
    if not trimmed:
        return unicodedata.normalize("NFC", os.path.normpath(actual_base_dir))
    if trimmed == "~":
        return unicodedata.normalize("NFC", str(Path.home()))
    if trimmed.startswith("~/"):
        return unicodedata.normalize("NFC", os.path.join(str(Path.home()), trimmed[2:]))

    if os.path.isabs(trimmed):
        return unicodedata.normalize("NFC", os.path.normpath(trimmed))
    return unicodedata.normalize("NFC", os.path.abspath(os.path.join(actual_base_dir, trimmed)))


def to_relative_path(absolute_path: str) -> str:
    """
    Port of toRelativePath() — relativize under cwd to save tokens; if outside
    cwd (would start with ..), keep the absolute path unchanged.
    """
    from optimus.utils.cwd import get_cwd

    try:
        relative_path = os.path.relpath(absolute_path, get_cwd())
    except ValueError:
        return absolute_path  # cross-drive on Windows
    return absolute_path if relative_path.startswith("..") else relative_path


def contains_path_traversal(path: str) -> bool:
    """Port of containsPathTraversal() — True if path navigates to a parent dir."""
    import re

    return re.search(r"(?:^|[\\/])\.\.(?:[\\/]|$)", path) is not None
