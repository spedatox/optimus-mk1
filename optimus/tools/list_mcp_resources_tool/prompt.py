"""Prompt text for ListMcpResourcesTool."""

LIST_MCP_RESOURCES_TOOL_NAME = "ListMcpResources"

DESCRIPTION = "List available resources from configured MCP servers."

PROMPT = """\
List available resources from configured MCP servers. Each returned resource
includes a `uri` (pass it to ReadMcpResource), name, MIME type, and the server
it belongs to. Pass `server` to filter to one server's resources.
"""
