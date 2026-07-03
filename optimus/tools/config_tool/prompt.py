"""Prompt text for ConfigTool."""

CONFIG_TOOL_NAME = "Config"

DESCRIPTION = "Get or set Optimus configuration settings."

PROMPT = """\
Get or set Optimus configuration settings (theme, verbosity, editor mode,
etc.). Settings persist in the global ~/.claude.json config file.

- To READ a setting: pass only `setting` (dot-separated for nested keys).
- To WRITE a setting: pass `setting` and `value`.

Only change settings the user asked you to change, and report the previous
value so the change is easy to undo.
"""
