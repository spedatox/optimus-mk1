"""Prompt text for TaskOutputTool."""

TASK_OUTPUT_TOOL_NAME = "TaskOutput"

DESCRIPTION = "Get output from a running or completed background task."

PROMPT = """\
Get output from a running or completed background task (background shell
commands, background agents).

- block=true (default) waits up to `timeout` ms for the task to finish and
  returns the full output.
- block=false returns immediately with the partial output so far.

If the wait times out, the partial output and current status are returned —
the task keeps running.
"""
