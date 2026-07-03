"""Prompt text for ExitWorktreeTool."""

EXIT_WORKTREE_TOOL_NAME = "ExitWorktree"

DESCRIPTION = "Exit the current git worktree and return to the original working directory."

PROMPT = """\
Exit the current git worktree and return to the original working directory.

- action='keep' leaves the worktree on disk (its branch and changes remain).
- action='remove' deletes it. If the worktree has uncommitted changes,
  removal is refused unless discard_changes=true is passed explicitly.
"""
