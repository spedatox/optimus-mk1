"""tools/powershell_tool/prompt.py — condensed port of src/tools/PowerShellTool/prompt.ts"""
from __future__ import annotations

POWERSHELL_TOOL_NAME = "PowerShell"

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000


def get_powershell_description() -> str:
    return f"""Executes a given PowerShell command with optional timeout.

Usage notes:
  - The command argument is required.
  - You can specify an optional timeout in milliseconds (up to {MAX_TIMEOUT_MS}ms / 10 minutes). Default {DEFAULT_TIMEOUT_MS}ms.
  - For file operations prefer the dedicated tools (Read/Write/Edit/Glob/Grep) over PowerShell where one fits.
  - Use ';' to chain commands; on Windows PowerShell 5.1 the '&&'/'||' operators are not available.
  - Do NOT use interactive commands (Read-Host, Get-Credential, pause) — this runs with -NonInteractive.
  - For git: prefer creating a new commit over amending; never skip hooks unless asked."""
