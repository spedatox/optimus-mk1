"""
utils/json.py — partial port of src/utils/json.ts + the stripBOM helper from
src/utils/jsonRead.ts.

safe_parse_json mirrors safeParseJSON: parse-or-None, never throws.
"""
from __future__ import annotations

import json as _stdlib_json
from typing import Any, Optional

UTF8_BOM = "﻿"


def strip_bom(content: str) -> str:
    """Mirrors stripBOM() — PowerShell 5.x prepends a BOM to UTF-8 files."""
    return content[1:] if content.startswith(UTF8_BOM) else content


def safe_parse_json(json_str: Optional[str], should_log_error: bool = True) -> Any:
    """
    Mirrors safeParseJSON(): return the parsed value, or None on empty input or
    a parse error. Strips a leading BOM first (matches safeParseJSONC behavior).
    """
    if not json_str:
        return None
    try:
        return _stdlib_json.loads(strip_bom(json_str))
    except (ValueError, TypeError):
        return None


def json_parse(data: str) -> Any:
    """
    Mirrors slowOperations.jsonParse — JSON.parse with no swallowing (raises on
    invalid). The TS variant adds perf timing; the parse semantics are identical.
    """
    return _stdlib_json.loads(data)


def json_stringify(value: Any, replacer: Any = None, space: Optional[int] = None) -> str:
    """
    Mirrors slowOperations.jsonStringify — JSON.stringify. `space` maps to
    indent. Keys are kept in insertion order (Python dict + ensure_ascii=False).
    """
    return _stdlib_json.dumps(value, indent=space, ensure_ascii=False)
