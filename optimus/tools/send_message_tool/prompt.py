"""Prompt text for SendMessageTool."""

SEND_MESSAGE_TOOL_NAME = "SendMessage"

DESCRIPTION = "Send a message to another agent in the swarm."

PROMPT = """\
Send a message to another agent in the swarm. Used for agent-to-agent
communication: plain text updates, shutdown requests/responses, and plan
approval responses.

- `to` is the recipient agent id or name.
- Response-type messages (shutdown_response, plan_approval_response) must echo
  the `request_id` they answer and set `approve`.
"""
