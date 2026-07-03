"""Prompt text for LSPTool."""

LSP_TOOL_NAME = "LSP"

DESCRIPTION = "Invoke a Language Server Protocol method for code intelligence."

PROMPT = """\
Invoke a Language Server Protocol method (e.g. textDocument/definition,
textDocument/references, textDocument/hover) against the workspace's language
server for code intelligence: go-to-definition, find-references, hover types,
and diagnostics.
"""
