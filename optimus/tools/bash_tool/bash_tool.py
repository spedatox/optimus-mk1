"""tools/bash_tool/bash_tool.py — core port of src/tools/BashTool/BashTool.tsx
(restored from commit f696afe, upgraded to the current Tool protocol).

Execute a bash command and capture stdout/stderr with a timeout. Mirrors the
PowerShellTool port's execution machinery; the two differ only in shell
resolution and prompt text.

Porting notes (core execution; deep machinery is RE-ENTRY):
  - bashSecurity / bashPermissions / heredoc rewriting / sandbox gating →
    RE-ENTRY (the 7588b87 infrastructure was dropped in the restructure). The
    query loop's can_use_tool is the outer permission gate; check_permissions
    returns 'ask' so shell commands prompt by default (fail-safe).
  - run_in_background → RE-ENTRY (foreground only; the flag is accepted so the
    schema matches, and ignored).
  - Shell resolution: $SHELL if it is bash, else `bash` on PATH (Git Bash on
    Windows, including the default install path), else /bin/sh.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.bash_tool.prompt import (
    BASH_TOOL_NAME,
    DEFAULT_TIMEOUT_MS,
    MAX_TIMEOUT_MS,
    get_bash_description,
)

_MAX_OUTPUT_CHARS = 30_000

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "The bash command to execute"},
        "timeout": {"type": "number", "description": f"Optional timeout in milliseconds (max {MAX_TIMEOUT_MS})"},
        "description": {"type": "string", "description": "Clear, concise description of what this command does in active voice."},
        "run_in_background": {"type": "boolean", "description": "Set to true to run this command in the background."},
        "dangerouslyDisableSandbox": {"type": "boolean", "description": "Override sandbox mode and run without sandboxing."},
    },
    "required": ["command"],
    "additionalProperties": False,
}

# Default Git-for-Windows bash locations, tried after PATH lookup fails.
_WINDOWS_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def _bash_invocation(command: str) -> list[str]:
    shell = os.environ.get("SHELL")
    if shell and os.path.basename(shell).startswith("bash") and os.path.exists(shell):
        return [shell, "-c", command]
    bash = shutil.which("bash")
    if bash:
        return [bash, "-c", command]
    for candidate in _WINDOWS_BASH_CANDIDATES:
        if os.path.exists(candidate):
            return [candidate, "-c", command]
    # Last resort so the tool degrades instead of hard-failing.
    return [shell or "/bin/sh", "-c", command]


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    head = _MAX_OUTPUT_CHARS - 200
    return text[:head] + f"\n\n[Output truncated — exceeded {_MAX_OUTPUT_CHARS} characters]"


@build_tool
class BashTool:
    name = BASH_TOOL_NAME
    search_hint = "execute bash / POSIX shell commands"
    max_result_size_chars = _MAX_OUTPUT_CHARS
    strict = True
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        if input and input.get("description"):
            return input["description"]
        return "Runs a bash command"

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return get_bash_description()

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
        # semantics / allowlist matching from bashPermissions.ts).
        return PermissionResult(behavior="ask", updated_input=input,
                                message="Run this bash command?")

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

        argv = _bash_invocation(command)
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
