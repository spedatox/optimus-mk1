"""Prompt text and limits for BashTool."""

BASH_TOOL_NAME = "Bash"

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000


def get_bash_description() -> str:
    return f"""\
Executes a given bash command and returns its output.

This tool runs POSIX sh/bash — on Windows it uses Git Bash when available.
Use Unix shell syntax: `/dev/null` not `NUL`, forward slashes, `$VAR`.

- Working directory persists between calls, but prefer absolute paths.
- Shell state (env vars, functions) does not persist between calls; the shell
  is initialized from the user's profile.
- IMPORTANT: Avoid using this tool to run `find`, `grep`, `cat`, `head`,
  `tail`, `sed`, `awk`, or `echo` commands unless a dedicated tool cannot
  accomplish your task — use the Glob, Grep, FileRead, and FileEdit tools
  instead.
- If the command will create new directories or files, first verify the parent
  directory exists.
- Always quote file paths that contain spaces with double quotes.
- You may specify an optional timeout in milliseconds (up to {MAX_TIMEOUT_MS}ms /
  10 minutes). By default, commands time out after {DEFAULT_TIMEOUT_MS}ms (2 minutes).
- When issuing multiple commands, chain dependent commands with `&&` in one
  call and make separate parallel calls for independent commands.

# Git
- Interactive flags (`-i`, e.g. `git rebase -i`, `git add -i`) are not
  supported in this environment.
- Commit or push only when the user asks. Prefer creating a new commit over
  amending. Never skip hooks (--no-verify) unless the user explicitly asks.
"""
