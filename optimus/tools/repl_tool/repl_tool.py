"""tools/repl_tool/repl_tool.py — port of src/tools/REPLTool (restored from
commit f696afe, upgraded to the current Tool protocol).

Executes Python in-process with a persistent namespace. The last expression's
value is echoed (true REPL semantics: the code is parsed once and, when the
final statement is an expression, it is evaluated separately so its repr can
be captured even in multi-statement snippets — an upgrade over the old
eval-or-exec approach, which only echoed single-expression inputs).
"""
from __future__ import annotations

import ast
import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.repl_tool.prompt import DESCRIPTION, PROMPT, REPL_TOOL_NAME

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "Python code to execute in the REPL"},
        "language": {
            "type": "string",
            "description": "Language for the REPL (currently only 'python' supported)",
        },
    },
    "required": ["code"],
    "additionalProperties": False,
}

# Persistent REPL namespace across calls in the same session.
_repl_globals: dict[str, Any] = {"__name__": "__repl__"}


def reset_repl_namespace() -> None:
    _repl_globals.clear()
    _repl_globals["__name__"] = "__repl__"


@build_tool
class REPLTool:
    name = REPL_TOOL_NAME
    search_hint = "run python snippets in a persistent interpreter"
    input_schema = _INPUT_SCHEMA
    input_json_schema = _INPUT_SCHEMA
    max_result_size_chars = 100_000
    strict = True
    should_defer = True

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        # Arbitrary Python can write anywhere — treat as a write.
        return False

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("code", "")

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        # In-process code execution is shell-equivalent — prompt by default.
        return PermissionResult(behavior="ask", updated_input=input,
                                message="Run this Python code in the REPL?")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        language = (input.get("language") or "python").lower()
        if language != "python":
            return ValidationResult.fail(f"Language '{language}' not supported.", error_code=1)
        if not input.get("code", "").strip():
            return ValidationResult.fail("code must not be empty", error_code=2)
        return ValidationResult.ok()

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        code: str = input["code"]
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        result_repr: Optional[str] = None
        error: Optional[str] = None

        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError:
            return ToolResult(data={"output": traceback.format_exc(limit=0), "isError": True})

        # Split off a trailing expression so its value can be echoed.
        trailing_expr: Optional[ast.Expression] = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            trailing_expr = ast.Expression(tree.body.pop().value)

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                if tree.body:
                    exec(compile(tree, "<repl>", "exec"), _repl_globals)
                if trailing_expr is not None:
                    value = eval(compile(trailing_expr, "<repl>", "eval"), _repl_globals)
                    if value is not None:
                        result_repr = repr(value)
        except Exception:
            error = traceback.format_exc()

        parts = [p for p in (stdout_buf.getvalue(), stderr_buf.getvalue()) if p]
        if error:
            parts.append(error)
        elif result_repr is not None:
            parts.append(result_repr)
        return ToolResult(data={"output": "".join(parts) or "(no output)",
                                "isError": error is not None})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "tool_result", "content": data["output"],
                                 "tool_use_id": tool_use_id}
        if data.get("isError"):
            block["is_error"] = True
        return block
