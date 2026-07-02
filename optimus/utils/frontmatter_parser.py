"""
utils/frontmatter_parser.py — partial port of src/utils/frontmatterParser.ts

parse_frontmatter extracts a leading YAML `---` block; split_path_in_frontmatter
splits a comma-separated path string (respecting `{...}` braces) and brace-expands.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Union

import yaml

FRONTMATTER_REGEX = re.compile(r"^---\s*\n([\s\S]*?)---\s*\n?")


def parse_frontmatter(markdown: str, source_path: Optional[str] = None) -> dict[str, Any]:
    """
    Returns {'frontmatter': dict, 'content': str}. On parse failure, frontmatter
    is {} (the raw retry-with-quoting path is folded into pyyaml's tolerance).
    """
    match = FRONTMATTER_REGEX.match(markdown)
    if not match:
        return {"frontmatter": {}, "content": markdown}

    frontmatter_text = match.group(1) or ""
    content = markdown[len(match.group(0)) :]

    frontmatter: dict[str, Any] = {}
    try:
        parsed = yaml.safe_load(frontmatter_text)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except yaml.YAMLError:
        from optimus.utils.debug import log_for_debugging

        location = f" in {source_path}" if source_path else ""
        log_for_debugging(
            f"Failed to parse YAML frontmatter{location}", {"level": "warn"}
        )

    return {"frontmatter": frontmatter, "content": content}


def _brace_expand(pattern: str) -> list[str]:
    """Expand `{a,b}` alternations, including nested ones (cartesian product)."""
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    options = m.group(1).split(",")
    results: list[str] = []
    for opt in options:
        expanded = pattern[: m.start()] + opt + pattern[m.end() :]
        results.extend(_brace_expand(expanded))
    return results


def split_path_in_frontmatter(input_value: Union[str, list[str]]) -> list[str]:
    """Split a comma-separated path string (braces respected) and brace-expand."""
    if isinstance(input_value, list):
        out: list[str] = []
        for item in input_value:
            out.extend(split_path_in_frontmatter(item))
        return out
    if not isinstance(input_value, str):
        return []

    parts: list[str] = []
    current = ""
    brace_depth = 0
    for char in input_value:
        if char == "{":
            brace_depth += 1
            current += char
        elif char == "}":
            brace_depth -= 1
            current += char
        elif char == "," and brace_depth == 0:
            trimmed = current.strip()
            if trimmed:
                parts.append(trimmed)
            current = ""
        else:
            current += char
    trimmed = current.strip()
    if trimmed:
        parts.append(trimmed)

    expanded: list[str] = []
    for part in parts:
        expanded.extend(_brace_expand(part))
    return expanded
