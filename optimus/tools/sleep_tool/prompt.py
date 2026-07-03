"""Prompt text for SleepTool."""

SLEEP_TOOL_NAME = "Sleep"

DESCRIPTION = "Pause for a specified duration without holding a shell process."

PROMPT = """\
Wait for a specified duration, then continue. The user can interrupt the sleep
at any time.

Prefer this tool over `sleep` shell commands — it does not occupy a shell
process while waiting and it responds to interrupts immediately.

Use it when polling for an external condition (e.g. waiting for a service to
come up before retrying) or when explicitly asked to wait. Do not use it to
pad time between steps that could run immediately.
"""
