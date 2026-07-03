# Optimus Mark I — Python port of Claude Code

# The Tool module ports src/Tool.ts and is imported as `optimus.tool`
# throughout the codebase, while the file on disk is lowercase tool.py
# (Python imports are case-sensitive even on Windows). Register the alias so
# both spellings resolve to the same module object.
import sys as _sys

from optimus import tool as _tool_module

_sys.modules.setdefault("optimus.tool", _tool_module)
