"""Prompt text for REPLTool."""

REPL_TOOL_NAME = "REPL"

DESCRIPTION = "Execute Python code in a persistent in-process REPL."

PROMPT = """\
Execute code in an in-process Python REPL and return the output.

The session is persistent: variables, functions, and imports defined in one
call are available in subsequent calls. The final expression's value is
returned (like a real REPL), along with anything printed to stdout/stderr.

Use it for quick calculations, data transformations, and verifying snippets.
Do NOT use it to touch files or run shell commands — use the file tools and
Bash/PowerShell for those, which go through proper permissioning.
"""
