"""Prompt text for SyntheticOutputTool (StructuredOutput)."""

SYNTHETIC_OUTPUT_TOOL_NAME = "StructuredOutput"

DESCRIPTION = "Return structured output in the requested format."

PROMPT = """\
Use this tool to return your final response in the requested structured format.
You MUST call this tool exactly once at the end of your response to provide the
structured output. The input must match the output schema the caller requested.
"""
