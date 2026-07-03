"""Prompt text for ToolSearchTool."""

TOOL_SEARCH_TOOL_NAME = "ToolSearch"

DESCRIPTION = "Fetches full schema definitions for deferred tools so they can be called."

PROMPT = """\
Fetches full schema definitions for deferred tools so they can be called.

Deferred tools appear by name in the tool list but their parameter schemas are
not loaded. Use this tool to fetch the schemas; once a tool's schema appears in
the result, it is callable exactly like any other tool.

Query forms:
- "select:Read,Edit,Grep" — fetch these exact tools by name
- "notebook jupyter" — keyword search, up to max_results best matches
- "+slack send" — require "slack" in the name, rank by remaining terms

Batch every tool you expect to need into ONE call — the select query accepts a
comma-separated list. Do not load tools one at a time.
"""
