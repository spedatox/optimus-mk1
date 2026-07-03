"""Prompt text for McpAuthTool."""

MCP_AUTH_TOOL_NAME = "McpAuth"

DESCRIPTION = "Manage OAuth authentication for MCP servers that require it."

PROMPT = """\
Manage OAuth authentication for MCP servers that require it.

Actions:
- start: begin the OAuth flow; returns the authorization URL for the user to
  open.
- complete: finish the flow with the authorization code the user obtained.
- status: check whether the server is authenticated.
"""
