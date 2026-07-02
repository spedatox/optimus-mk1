"""
tools/powershell_tool/powershell_tool.py — core port of src/tools/PowerShellTool/PowerShellTool.tsx

Execute a PowerShell command and capture stdout/stderr with a timeout.

Porting notes (core execution; deep machinery is RE-ENTRY):
  - The ~7800 lines of powershellSecurity / powershellPermissions / pathValidation
    / readOnlyValidation / gitSafety / sandbox gating → RE-ENTRY. The query loop's
    can_use_tool is the outer permission gate; check_permissions returns 'ask' so
    shell commands prompt by default (fail-safe).
  - run_in_background / auto-backgrounding / output persistence → RE-ENTRY (runs
    foreground here). dangerouslyDisableSandbox accepted but unused.
  - Output is truncated to max_result_size_chars (30K).
  - Uses pwsh if available, else powershell.exe (Windows); falls back to a POSIX
    shell only if neither exists (so the tool degrades rather than hard-fails).
"""
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Optional

from optimus.Tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.powershell_tool.prompt import (
    DEFAULT_TIMEOUT_MS,
    MAX_TIMEOUT_MS,
    POWERSHELL_TOOL_NAME,
    get_powershell_description,
)

_MAX_OUTPUT_CHARS = 30_000

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "The PowerShell command to execute"},
        "timeout": {"type": "number", "description": f"Optional timeout in milliseconds (max {MAX_TIMEOUT_MS})"},
        "description": {"type": "string", "description": "Clear, concise description of what this command does in active voice."},
        "run_in_background": {"type": "boolean", "description": "Set to true to run this command in the background."},
        "dangerouslyDisableSandbox": {"type": "boolean", "description": "Override sandbox mode and run without sandboxing."},
    },
    "required": ["command"],
    "additionalProperties": False,
}


def _powershell_invocation(command: str) -> list[str]:
    pwsh = shutil.which("pwsh")
    if pwsh:
        return [pwsh, "-NoProfile", "-NonInteractive", "-Command", command]
    powershell = shutil.which("powershell")
    if powershell:
        return [powershell, "-NoProfile", "-NonInteractive", "-Command", command]
    # Last resort so the tool degrades instead of hard-failing off Windows.
    shell = os.environ.get("SHELL") or "/bin/sh"
    return [shell, "-c", command]


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    head = _MAX_OUTPUT_CHARS - 200
    return text[:head] + f"\n\n[Output truncated — exceeded {_MAX_OUTPUT_CHARS} characters]"


@build_tool
class PowerShellTool:
    name = POWERSHELL_TOOL_NAME
    search_hint = "execute Windows PowerShell commands"
    max_result_size_chars = _MAX_OUTPUT_CHARS
    strict = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        if input and input.get("description"):
            return input["description"]
        return "Runs a PowerShell command"

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_powershell_description()

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return False

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return False

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("command", "")

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        if input and input.get("description"):
            return input["description"]
        return "Running command"

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        # Fail-safe: shell execution prompts by default (RE-ENTRY: full command
        # semantics / allowlist matching from powershellPermissions.ts).
        return PermissionResult(behavior="ask", updated_input=input,
                                message="Run this PowerShell command?")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        if not input.get("command", "").strip():
            return ValidationResult.fail("Command must not be empty.", error_code=1)
        return ValidationResult.ok()

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        command = input["command"]
        timeout_ms = min(input.get("timeout") or DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS)

        from optimus.utils.cwd import get_cwd

        argv = _powershell_invocation(command)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=get_cwd(),
            )
        except OSError as e:
            return ToolResult(
                data={"stdout": "", "stderr": f"Failed to launch shell: {e}", "interrupted": False}
            )

        interrupted = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            interrupted = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            stdout_b, stderr_b = b"", b""
        except asyncio.CancelledError:
            interrupted = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise

        stdout = _truncate(stdout_b.decode("utf-8", errors="replace"))
        stderr = _truncate(stderr_b.decode("utf-8", errors="replace"))
        if interrupted and not stderr:
            stderr = f"Command timed out after {timeout_ms}ms"

        return ToolResult(
            data={
                "stdout": stdout,
                "stderr": stderr,
                "interrupted": interrupted,
                "returnCode": proc.returncode,
            }
        )

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        parts = []
        if data.get("stdout"):
            parts.append(data["stdout"])
        if data.get("stderr"):
            parts.append(data["stderr"])
        content = "\n".join(parts).strip() or "(no output)"
        is_error = bool(data.get("interrupted")) or (data.get("returnCode") not in (0, None))
        block: dict[str, Any] = {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
        if is_error:
            block["is_error"] = True
        return block
