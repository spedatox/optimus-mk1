"""Prompt text for ExitPlanModeTool."""

EXIT_PLAN_MODE_TOOL_NAME = "ExitPlanMode"

DESCRIPTION = (
    "Prompts the user to exit plan mode and start coding. Use this only after "
    "you have presented the implementation plan."
)

PROMPT = """\
Use this tool when you are in plan mode and have finished writing your plan to
the user. This will prompt the user to confirm the plan and exit plan mode.
Provide the final plan in the `plan` parameter — it is shown to the user for
approval.

IMPORTANT: Only use this tool when the task requires planning the implementation
steps of a task that requires writing code. For research tasks where you're
gathering information, searching files, reading files or in general trying to
understand the codebase — do NOT use this tool.

Rules:
- The plan should be concise and information-dense, not padded.
- Include concrete file paths and the changes planned for each.
- Do not start implementing before the user approves the plan.
"""
