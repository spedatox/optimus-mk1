"""tools/lsp_tool/lsp_tool.py — port of src/tools/LSPTool (restored from commit
f696afe, upgraded to the current Tool protocol).

The TS source constructs per-server LSP tools once a language server is
connected; the connection stack (plugin LSP servers, transport, lifecycle) is
not yet ported. This tool carries the stable request surface: a registered
LSP client (register_lsp_client) receives raw method/params requests. Until a
client is registered, is_enabled() is False so the tool stays out of the pool
— matching how the source only exposes LSP tools for connected servers.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.lsp_tool.prompt import DESCRIPTION, LSP_TOOL_NAME, PROMPT

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "description": "LSP method to invoke (e.g. textDocument/definition)"},
        "params": {"type": "object", "description": "LSP method parameters"},
    },
    "required": ["method"],
    "additionalProperties": False,
}

# RE-ENTRY: set by the LSP connection stack (services/lsp) once ported.
_lsp_client: Optional[Any] = None


def register_lsp_client(client: Any) -> None:
    """Register the workspace language-server client (must expose
    `async request(method, params)`)."""
    global _lsp_client
    _lsp_client = client


def get_lsp_client() -> Optional[Any]:
    return _lsp_client


@build_tool
class LSPTool:
    name = LSP_TOOL_NAME
    search_hint = "code intelligence via language server"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    is_lsp = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_enabled(self) -> bool:
        # Only exposed once a language server is connected (mirrors the source,
        # where LSP tools exist per connected server).
        return _lsp_client is not None

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("method", "").strip():
            return ValidationResult.fail("method must not be empty", error_code=1)
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
        if _lsp_client is None:
            return ToolResult(data={"error": (
                "No language server is connected. LSP tools become available "
                "once a workspace language server is registered."
            )})
        try:
            result = await _lsp_client.request(input["method"], input.get("params") or {})
        except Exception as exc:
            return ToolResult(data={"error": f"LSP request failed: {exc}"})
        return ToolResult(data={"result": result})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result", "content": json.dumps(data["result"], default=str),
                "tool_use_id": tool_use_id}
