"""Prompt text for SkillTool."""

SKILL_TOOL_NAME = "Skill"

DESCRIPTION = "Execute a skill (slash command) within the main conversation."

PROMPT = """\
Execute a skill within the main conversation.

When the user asks you to perform a task that matches an available skill, or
references a "slash command" / types `/<name>`, use this tool to invoke it.

How to invoke:
- Set `skill` to the exact name of an available skill (no leading slash).
- Set `args` to pass optional arguments.

Important:
- Only invoke a skill that appears in the available-commands list or that the
  user explicitly typed as `/<name>`. Never guess or invent skill names.
- The result is the skill's expanded prompt — follow those instructions
  directly as part of the current turn.
"""
