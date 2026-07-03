"""Prompt text for EnterWorktreeTool."""

ENTER_WORKTREE_TOOL_NAME = "EnterWorktree"

DESCRIPTION = "Create a git worktree and switch the session's working directory into it."

PROMPT = """\
Create a new git worktree and switch the session's working directory to it.
This gives you an isolated copy of the repository on its own branch, so you
can work without affecting the main working tree.

- `name` is optional; each '/'-separated segment may contain only letters,
  digits, dots, underscores, and dashes (max 64 chars total). A random name is
  generated when omitted.
- The worktree is created under `<repo-parent>/.worktrees/<name>` on a new
  branch `optimus/<name>`.
- Use ExitWorktree to return to the original tree (keeping or removing the
  worktree).
"""
