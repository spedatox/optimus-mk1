"""Prompt text for BriefTool."""

BRIEF_TOOL_NAME = "Brief"

DESCRIPTION = "Send a status message to the user, optionally with file attachments."

PROMPT = """\
Send a message to the user. Use this to surface task completion, blockers, or
status updates from long-running/background work. Supports markdown.

- status='normal' when replying to something the user just said.
- status='proactive' for unsolicited updates (task finished in the background,
  a blocker appeared).
- attachments: optional file paths shown alongside the message.
"""
