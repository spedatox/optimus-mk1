"""
utils/file_read.py — partial port of src/utils/fileRead.ts

read_file_sync_with_metadata mirrors readFileSyncWithMetadata: read a text file,
CRLF-normalize the content (so it matches what's stored in readFileState), and
report the detected encoding. Plus the shared ReadFileState store.

Porting note: encoding detection is simplified to utf-8 (with latin-1 fallback);
the TS version sniffs BOM/charset. Binary detection is a NUL-byte heuristic.
"""
from __future__ import annotations

import os
from typing import Any, Optional


class ReadFileState(dict):
    """
    Maps absolute file path → {content, timestamp, offset, limit, isPartialView}.
    A plain dict with get/set semantics; mirrors the readFileState Map. Tools use
    it to enforce read-before-write and detect external modification.
    """


def read_file_sync_with_metadata(file_path: str) -> dict[str, Any]:
    """
    Read a text file; return {'content', 'encoding', 'line_endings'}.

    Mirrors readFileSyncWithMetadata: content is CRLF-normalized (so it matches
    what's stored in readFileState), and line_endings is detected from the raw
    bytes *before* normalization so callers can preserve the original EOL
    convention on write-back.
    """
    with open(file_path, "rb") as f:
        raw = f.read()
    try:
        content = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
        encoding = "latin-1"
    line_endings = "CRLF" if b"\r\n" in raw else "LF"
    content = content.replace("\r\n", "\n")
    return {"content": content, "encoding": encoding, "line_endings": line_endings}


def detect_line_endings(content: str) -> str:
    """Return 'CRLF' if the original used Windows line endings, else 'LF'."""
    return "CRLF" if "\r\n" in content else "LF"


def is_probably_binary(file_path: str) -> bool:
    """Heuristic: a NUL byte in the first 8KB marks a binary file."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
        return b"\0" in chunk
    except OSError:
        return False
