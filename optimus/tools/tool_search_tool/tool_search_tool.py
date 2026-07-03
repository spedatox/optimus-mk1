"""tools/tool_search_tool/tool_search_tool.py — port of src/tools/ToolSearchTool
(restored from commit f696afe, upgraded to the current Tool protocol).

Searches the session's tool pool (context.options.tools) and returns full JSON
schemas for the matches, letting the model "load" deferred tools. Supports
exact selection ("select:A,B"), required-term prefix ("+slack send"), and
keyword scoring over name / search_hint / description-ish text.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.tool_search_tool.prompt import (
    DESCRIPTION,
    PROMPT,
    TOOL_SEARCH_TOOL_NAME,
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                'Query to find deferred tools. Use "select:<tool_name>" for direct '
                "selection, or keywords to search."
            ),
        },
        "max_results": {
            "type": "number",
            "description": "Maximum number of results to return (default: 5)",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


def _searchable_text(tool: Any) -> str:
    parts = [getattr(tool, "name", "") or ""]
    hint = getattr(tool, "search_hint", None)
    if hint:
        parts.append(hint)
    return " ".join(parts).lower()


def _score_tool(tool: Any, terms: list[str]) -> float:
    name = (getattr(tool, "name", "") or "").lower()
    text = _searchable_text(tool)
    score = 0.0
    for term in terms:
        if term in name:
            score += 2.0
        elif term in text:
            score += 1.0
    return score


@build_tool
class ToolSearchTool:
    name = TOOL_SEARCH_TOOL_NAME
    search_hint = "load deferred tool schemas by name or keyword"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    always_load = True  # the searcher itself is never deferred

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("query", "")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("query", "").strip():
            return ValidationResult.fail("query must not be empty", error_code=1)
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        query: str = input["query"].strip()
        max_results = int(input.get("max_results") or 5)
        all_tools = list(context.options.tools or [])

        if query.startswith("select:"):
            names = [n.strip() for n in query[len("select:"):].split(",") if n.strip()]
            matched = [t for t in all_tools if t.name in names]
            missing = [n for n in names if not any(t.name == n for t in all_tools)]
        else:
            terms = [t.lower() for t in re.split(r"[\s,]+", query) if t]
            required = [t[1:] for t in terms if t.startswith("+") and len(t) > 1]
            terms = [t.lstrip("+") for t in terms if t.lstrip("+")]
            candidates = all_tools
            if required:
                candidates = [
                    t for t in candidates
                    if all(r in (t.name or "").lower() for r in required)
                ]
            scored = [(t, _score_tool(t, terms)) for t in candidates]
            scored.sort(key=lambda x: x[1], reverse=True)
            matched = [t for t, s in scored if s > 0][:max_results]
            missing = []

        schemas = []
        for tool in matched[:max_results]:
            try:
                desc = await tool.description({}, {})
            except Exception:
                desc = getattr(tool, "search_hint", "") or ""
            schemas.append({
                "name": tool.name,
                "description": desc,
                "input_schema": tool.input_schema,
            })

        return ToolResult(data={
            "query": query,
            "matches": [s["name"] for s in schemas],
            "missing": missing,
            "schemas": schemas,
            "total_tools": len(all_tools),
        })

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if not data.get("schemas"):
            content = (
                f"No tools matched query '{data.get('query', '')}'. "
                f"{len(data.get('missing', []))} requested names were unknown."
            )
            return {"type": "tool_result", "content": content,
                    "tool_use_id": tool_use_id, "is_error": True}
        lines = ["<functions>"]
        for s in data["schemas"]:
            lines.append(f"<function>{json.dumps(s)}</function>")
        lines.append("</functions>")
        if data.get("missing"):
            lines.append(f"Unknown tool names: {', '.join(data['missing'])}")
        return {"type": "tool_result", "content": "\n".join(lines), "tool_use_id": tool_use_id}
