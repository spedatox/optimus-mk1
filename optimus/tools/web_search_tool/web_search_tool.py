"""
tools/web_search_tool/web_search_tool.py — port of src/tools/WebSearchTool/WebSearchTool.ts

Search the web via the Anthropic server-side web_search tool, returning hits +
the model's commentary. Read-only.

Porting notes:
  - queryModelWithStreaming(extraToolSchemas=[web_search]) → a single
    optimus.api.run_web_search() call (non-streaming) that returns the response
    content blocks; makeOutputFromSearchResponse parsing is preserved.
  - checkPermissions 'passthrough' → 'ask' (web search prompts by default).
  - feature gating / provider checks → is_enabled True.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from optimus.api import run_web_search
from optimus.Tool import PermissionResult, ToolResult, ToolUseContext, ValidationResult, build_tool
from optimus.tools.web_search_tool.prompt import WEB_SEARCH_TOOL_NAME, get_web_search_prompt

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "description": "The search query to use"},
        "allowed_domains": {"type": "array", "items": {"type": "string"}, "description": "Only include results from these domains"},
        "blocked_domains": {"type": "array", "items": {"type": "string"}, "description": "Never include results from these domains"},
    },
    "required": ["query"],
    "additionalProperties": False,
}


def _block_type(block: Any) -> Optional[str]:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _make_output(blocks: list[Any], query: str, duration_seconds: float) -> dict[str, Any]:
    """Parse server response blocks into {query, results, durationSeconds}."""
    results: list[Any] = []
    text_acc = ""
    in_text = True

    for block in blocks:
        btype = _block_type(block)
        if btype == "server_tool_use":
            if in_text:
                in_text = False
                if text_acc.strip():
                    results.append(text_acc.strip())
                text_acc = ""
            continue
        if btype == "web_search_tool_result":
            content = block.get("content") if isinstance(block, dict) else getattr(block, "content", None)
            if not isinstance(content, list):
                err = getattr(content, "error_code", None) or "unknown"
                results.append(f"Web search error: {err}")
                continue
            hits = []
            for r in content:
                title = r.get("title") if isinstance(r, dict) else getattr(r, "title", "")
                url = r.get("url") if isinstance(r, dict) else getattr(r, "url", "")
                hits.append({"title": title, "url": url})
            tool_use_id = block.get("tool_use_id") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
            results.append({"tool_use_id": tool_use_id, "content": hits})
        if btype == "text":
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", "")
            if in_text:
                text_acc += text
            else:
                in_text = True
                text_acc = text

    if text_acc:
        results.append(text_acc.strip())
    return {"query": query, "results": results, "durationSeconds": duration_seconds}


@build_tool
class WebSearchTool:
    name = WEB_SEARCH_TOOL_NAME
    search_hint = "search the web for current information"
    max_result_size_chars = 100_000
    should_defer = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        q = (input or {}).get("query", "")
        return f"Search the web for: {q}" if q else "Search the web"

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_web_search_prompt()

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return "Web Search"

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("query", "")

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Searching the web"

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        query = input.get("query", "")
        if not query:
            return ValidationResult.fail("Error: Missing query", error_code=1)
        if input.get("allowed_domains") and input.get("blocked_domains"):
            return ValidationResult.fail(
                "Error: Cannot specify both allowed_domains and blocked_domains in the same request",
                error_code=2,
            )
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="ask", updated_input=input, message="Allow a web search?")

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        start = time.time()
        blocks = await run_web_search(
            input["query"],
            allowed_domains=input.get("allowed_domains"),
            blocked_domains=input.get("blocked_domains"),
        )
        output = _make_output(blocks, input["query"], time.time() - start)
        return ToolResult(data=output)

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        lines: list[str] = []
        for entry in data["results"]:
            if isinstance(entry, str):
                lines.append(entry)
            elif isinstance(entry, dict) and "content" in entry:
                for hit in entry["content"]:
                    lines.append(f"- [{hit['title']}]({hit['url']})")
        content = "\n".join(lines).strip() or "No results found"
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
